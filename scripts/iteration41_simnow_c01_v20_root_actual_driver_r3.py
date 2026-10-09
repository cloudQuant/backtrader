"""Parent-owned V20 C01 child-call and outer-close receipt contracts.

This module is the fixed parent-side boundary for one V20 child invocation.
The child returns a bounded public candidate projection on stdout and writes
one opaque RootSeal frame to a separate inherited pipe. Neither channel is
authority by itself. A formal C01 result is possible only after the caller
binds both channels to one clean Job/process lifecycle, verifies the held
source map before and after a normal CUv2 close, and consumes the Root
adjudicator's one-use proof.

The receipt APIs below are pure Python and perform no process, WinAPI,
provider, SDK/native, private-config, or filesystem operation. The Root-only
production caller owns those operations.
"""

from __future__ import annotations

import json
import hashlib
import io
import ntpath
import os
import re
import subprocess
import threading
import time
from types import FunctionType, GeneratorType, MappingProxyType, ModuleType
from typing import Any, Mapping


MODULE_NAME = "_c01_v20_root_actual_driver"
PROFILE_ID = "C01_NATIVE_TD_READ_V20"
CASE_ID = "C01"
MAX_PUBLIC_PROJECTION_BYTES = 256 * 1024
MAX_STDERR_BYTES = 64 * 1024
MAX_FRAME_BYTES = 18_087_964
MAX_SOURCE_ROWS = 256
CUV2_SOURCE_PATH = "D:/temp/iteration41-root-public-custody-v2.py"
CUV2_SOURCE_SHA256 = "e856be8e4056835d4a7e54f5c6b449c69ab3f1c2ebb049bcbcc1c95a9ad3f246"
CUV2_SOURCE_BYTES = 2344
_ROOT_PATH = "backtrader_runtime/certification_simnow_c01_root_v17.py"
_WRAPPER_PATH = "scripts/run_simnow_c01_native_td_read_v20_root_activation_r2.py"
_HANDOFF_PATH = "backtrader_runtime/certification_simnow_c01_rootseal_custody_v1.py"
_ADJUDICATOR_PATH = "backtrader_runtime/certification_simnow_c01_root_formal_adjudicator_v1.py"
_COMPLETION_PATH = (
    "examples/000_live_certification/simnow_penetration/common/c01_root_completion_v1.py"
)
_DRIVER_PATH = "scripts/iteration41_simnow_c01_v20_root_actual_driver_r3.py"
_JOB_BACKEND_PATH = "scripts/ctp_i13_i15_windows_job_backend.py"
_PYTHON_EXE_PATH = "C:/anaconda3/python.exe"
_PYTHON_DLL_PATH = "C:/anaconda3/python311.dll"
_PYTHON_EXE_SHA256 = "c98caee82c66433f0e89d4abbf152b39a7dc2e99979b28dcb021598b4e3f5642"
_PYTHON_DLL_SHA256 = "162e8557fbed5f39ae24983ee62b2d435b4796c937d9c1a34371888c7e43af00"
_CHILD_TIMEOUT_SECONDS = 180.0
_JOB_ZERO_TIMEOUT_SECONDS = 12.0
_FORCED_REAP_TIMEOUT_SECONDS = 8.0
_READER_JOIN_TIMEOUT_SECONDS = 8.0
_JOB_ZERO_POLL_SECONDS = 0.05
_BOOTSTRAP_SENTINEL = "_c01_v20_frame_channel_bootstrap"
_BOOTSTRAP_HANDLE = "_c01_v20_frame_channel_handle"
_BOOTSTRAP_MODE = "_c01_v20_child_mode"
_GATE_ID = "C01_V20_CREDENTIAL_FREE_JOB_CHANNEL_R1"
_GATE_MODES = frozenset({"activation", "credential_free_gate"})
_CHILD_WRAPPER_PATH = (
    r"D:\source_code\backtrader\scripts\run_simnow_c01_native_td_read_v20_root_activation_r2.py"
)
_ROOT_DIRECTORY = "D:/source_code/backtrader"
_OUTER_KEEPALIVE: list[tuple[Any, ...]] = []
_PARENT_NATIVE_KEEPALIVE: list[tuple[Any, ...]] = []
_ACTIVATION_LOCK = threading.Lock()
_HOST_ACTIVATION_STATE: dict[str, Any] = {
    "used": False,
    "lease": None,
    "call_nonce": None,
    "gate_receipt": None,
}
_CREDENTIAL_FREE_GATE_LOCK = threading.Lock()
_CREDENTIAL_FREE_GATE_STATE: dict[str, Any] = {"used": False, "receipt": None}
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_SAFE_REASON_RE = re.compile(r"[a-z0-9_:-]{1,96}\Z")
_PROCESS_FACTORY = object()
_OUTER_LEASE_FACTORY = object()
_OUTER_CLOSE_FACTORY = object()
_GATE_RECEIPT_FACTORY = object()
_PARENT_NATIVE_STATE_FACTORY = object()
_PROJECTION_KEYS = frozenset(
    {
        "case_id",
        "certification",
        "mode",
        "profile",
        "reason",
        "write_policy",
        "writes",
        "receipt_type",
        "receipt_verified",
        "source_closure_verified",
        "root_postverify_verified",
        "request_count",
        "query_callback_count",
        "snapshot_count",
        "write_invocation_count",
        "outer_job_empty",
        "stdout_eof",
        "stderr_eof",
        "stderr_empty",
        "job_handles_closed",
        "reader_threads_joined",
        "cleanup_verified",
    }
)
_PARENT_PROJECTION_KEYS = frozenset(
    {
        "outer_job_empty",
        "stdout_eof",
        "stderr_eof",
        "stderr_empty",
        "job_handles_closed",
        "reader_threads_joined",
        "cleanup_verified",
    }
)


class RootDriverError(ValueError):
    """Fixed, non-sensitive driver contract failure."""

    def __init__(self, code: str = "root_driver_blocked") -> None:
        if type(code) is not str or not code or not code.isascii():
            code = "root_driver_blocked"
        super().__init__(code)
        self.code = code


class _ParentLaunchError(RuntimeError):
    """Internal fixed-code failure from the parent Win32 lifecycle."""

    def __init__(self, code: str, *, controls: Any = None, uncertain: bool = False):
        self.code = code if type(code) is str and code.isascii() else "parent_launch_failed"
        self.controls = controls
        self.uncertain = uncertain
        super().__init__(self.code)


class _PipeCapture:
    """Bounded byte capture drained on one dedicated reader thread."""

    __slots__ = ("stream", "maximum", "data", "eof", "closed", "overflow", "failed", "thread")

    def __init__(self, stream: Any, maximum: int) -> None:
        self.stream = stream
        self.maximum = maximum
        self.data = bytearray()
        self.eof = False
        self.closed = False
        self.overflow = False
        self.failed = False
        self.thread: threading.Thread | None = None


class _ParentProcessControls:
    """Exact parent controls and attribute-list storage for one suspended child."""

    __slots__ = (
        "job",
        "process",
        "thread",
        "pid",
        "tid",
        "attribute_list",
        "attribute_storage",
        "job_array",
        "handle_array",
        "created",
        "resumed",
        "process_closed",
        "thread_closed",
        "job_closed",
        "forced",
    )

    def __init__(
        self,
        *,
        job: int,
        process: int,
        thread: int,
        pid: int,
        tid: int,
        attribute_list: Any,
        attribute_storage: Any,
        job_array: Any,
        handle_array: Any,
        created: bool,
    ) -> None:
        self.job = job
        self.process = process
        self.thread = thread
        self.pid = pid
        self.tid = tid
        self.attribute_list = attribute_list
        self.attribute_storage = attribute_storage
        self.job_array = job_array
        self.handle_array = handle_array
        self.created = created
        self.resumed = False
        self.process_closed = False
        self.thread_closed = False
        self.job_closed = False
        self.forced = False


class C01V20ParentProcessReceipt:
    """Parent-local evidence for one child call, with private frame retained."""

    __slots__ = (
        "frame",
        "handoff_module",
        "call_nonce",
        "stdout_raw",
        "stderr_raw",
        "child_pid",
        "exit_code",
        "launch_count",
        "job_assigned_before_resume",
        "job_empty",
        "stdout_eof",
        "stderr_eof",
        "frame_eof",
        "frame_payload_bytes",
        "job_handles_closed",
        "reader_threads_joined",
        "overflow_observed",
        "reader_failed",
        "forced_termination",
        "_factory",
    )

    def __init__(self, *, values: dict[str, Any], _factory: Any = None) -> None:
        if _factory is not _PROCESS_FACTORY or type(values) is not dict:
            raise RootDriverError("parent_process_receipt_factory_required")
        expected = {
            "frame",
            "handoff_module",
            "call_nonce",
            "stdout_raw",
            "stderr_raw",
            "child_pid",
            "exit_code",
            "launch_count",
            "job_assigned_before_resume",
            "job_empty",
            "stdout_eof",
            "stderr_eof",
            "frame_eof",
            "frame_payload_bytes",
            "job_handles_closed",
            "reader_threads_joined",
            "overflow_observed",
            "reader_failed",
            "forced_termination",
        }
        if set(values) != expected:
            raise RootDriverError("parent_process_receipt_shape_invalid")
        for name, value in values.items():
            object.__setattr__(self, name, value)
        object.__setattr__(self, "_factory", _PROCESS_FACTORY)
        if validate_c01_v20_parent_process_receipt(self) is not True:
            raise RootDriverError("parent_process_receipt_invalid")

    def __setattr__(self, _name: str, _value: Any) -> None:
        raise AttributeError("C01V20ParentProcessReceipt is immutable")

    def __repr__(self) -> str:
        return "C01V20ParentProcessReceipt(<one parent-held child call; frame redacted>)"


class C01V20CredentialFreeGateReceipt:
    """Typed, one-call result for the separate credential-free host gate."""

    __slots__ = (
        "status",
        "reason",
        "os_profile_matches",
        "environment_allowlist_verified",
        "credential_names_absent",
        "frame_payload_bytes",
        "writes",
        "formal_c01_pass",
        "official_c01_pass_count",
        "forced_cleanup",
        "outer_postverify_verified",
        "outer_close_verified",
        "cleanup_verified",
        "outer_job_empty",
        "stdout_eof",
        "stderr_eof",
        "stderr_empty",
        "frame_eof",
        "job_handles_closed",
        "reader_threads_joined",
        "exit_code",
        "_process_receipt",
        "_outer_close_receipt",
        "_factory",
    )

    def __init__(self, *, values: dict[str, Any], _factory: Any = None) -> None:
        if _factory is not _GATE_RECEIPT_FACTORY or type(values) is not dict:
            raise RootDriverError("credential_free_gate_receipt_factory_required")
        expected = {
            "status",
            "reason",
            "os_profile_matches",
            "environment_allowlist_verified",
            "credential_names_absent",
            "frame_payload_bytes",
            "writes",
            "formal_c01_pass",
            "official_c01_pass_count",
            "forced_cleanup",
            "outer_postverify_verified",
            "outer_close_verified",
            "cleanup_verified",
            "outer_job_empty",
            "stdout_eof",
            "stderr_eof",
            "stderr_empty",
            "frame_eof",
            "job_handles_closed",
            "reader_threads_joined",
            "exit_code",
            "_process_receipt",
            "_outer_close_receipt",
        }
        if set(values) != expected:
            raise RootDriverError("credential_free_gate_receipt_shape_invalid")
        for name, value in values.items():
            object.__setattr__(self, name, value)
        object.__setattr__(self, "_factory", _GATE_RECEIPT_FACTORY)
        if validate_c01_v20_credential_free_gate_receipt(self) is not True:
            raise RootDriverError("credential_free_gate_receipt_invalid")

    def __setattr__(self, _name: str, _value: Any) -> None:
        raise AttributeError("C01V20CredentialFreeGateReceipt is immutable")

    def __repr__(self) -> str:
        return f"C01V20CredentialFreeGateReceipt(status={self.status!r}, reason={self.reason!r})"


def create_c01_v20_parent_process_receipt(
    *,
    frame: Any,
    handoff_module: ModuleType,
    call_nonce: object,
    stdout_raw: bytes,
    stderr_raw: bytes,
    child_pid: int,
    exit_code: int,
    launch_count: int,
    job_assigned_before_resume: bool,
    job_empty: bool,
    stdout_eof: bool,
    stderr_eof: bool,
    frame_eof: bool,
    frame_payload_bytes: int,
    job_handles_closed: bool,
    reader_threads_joined: bool,
    overflow_observed: bool,
    reader_failed: bool,
    forced_termination: bool,
) -> C01V20ParentProcessReceipt:
    """Create a typed snapshot after the parent drains and closes all channels."""

    return C01V20ParentProcessReceipt(
        values={
            "frame": frame,
            "handoff_module": handoff_module,
            "call_nonce": call_nonce,
            "stdout_raw": stdout_raw,
            "stderr_raw": stderr_raw,
            "child_pid": child_pid,
            "exit_code": exit_code,
            "launch_count": launch_count,
            "job_assigned_before_resume": job_assigned_before_resume,
            "job_empty": job_empty,
            "stdout_eof": stdout_eof,
            "stderr_eof": stderr_eof,
            "frame_eof": frame_eof,
            "frame_payload_bytes": frame_payload_bytes,
            "job_handles_closed": job_handles_closed,
            "reader_threads_joined": reader_threads_joined,
            "overflow_observed": overflow_observed,
            "reader_failed": reader_failed,
            "forced_termination": forced_termination,
        },
        _factory=_PROCESS_FACTORY,
    )


def validate_c01_v20_parent_process_receipt(receipt: Any) -> bool:
    """Check one exact finite child projection and clean single-child lifecycle.

    A cleanly contained BLOCKED child may also have a nonzero exit code and no
    content frame.  Such a receipt permits source cleanup only; the wrapper
    and Root adjudicators require the candidate projection, a frame, and exit
    code zero before they can mint any formal result.
    """

    try:
        if (
            type(receipt) is not C01V20ParentProcessReceipt
            or receipt._factory is not _PROCESS_FACTORY
            or type(receipt.handoff_module) is not ModuleType
            or receipt.handoff_module.__name__
            != "backtrader_runtime.certification_simnow_c01_rootseal_custody_v1"
            or type(receipt.call_nonce) is not object
            or (
                receipt.frame is not None
                and (
                    type(receipt.frame)
                    is not receipt.handoff_module.__dict__.get("RootContentFrame")
                    or getattr(receipt.frame, "_factory", None)
                    is not receipt.handoff_module.__dict__.get("_FRAME_FACTORY")
                    or type(getattr(receipt.frame, "_raw", None)) is not bytes
                    or not 1
                    <= len(receipt.frame._raw)
                    <= receipt.handoff_module.__dict__.get("_MAX_FRAME_BYTES", 0)
                )
            )
            or type(receipt.stdout_raw) is not bytes
            or not 0 < len(receipt.stdout_raw) <= 64 * 1024
            or type(receipt.stderr_raw) is not bytes
            or receipt.stderr_raw != b""
            or type(receipt.child_pid) is not int
            or receipt.child_pid <= 0
            or type(receipt.exit_code) is not int
            or receipt.exit_code < 0
            or type(receipt.launch_count) is not int
            or receipt.launch_count != 1
            or any(
                getattr(receipt, field) is not True
                for field in (
                    "job_assigned_before_resume",
                    "job_empty",
                    "stdout_eof",
                    "stderr_eof",
                    "frame_eof",
                    "job_handles_closed",
                    "reader_threads_joined",
                )
            )
            or receipt.overflow_observed is not False
            or receipt.reader_failed is not False
            or type(receipt.forced_termination) is not bool
            or type(receipt.frame_payload_bytes) is not int
            or receipt.frame_payload_bytes < 0
        ):
            return False
        projection = _parse_canonical_projection(receipt.stdout_raw)
        is_gate_projection = _validate_credential_free_gate_projection(projection)
        if is_gate_projection:
            if receipt.frame is not None or receipt.frame_payload_bytes != 0:
                return False
            if receipt.forced_termination is True:
                return True
            return (projection["status"] == "PASS" and receipt.exit_code == 0) or (
                projection["status"] == "BLOCKED" and receipt.exit_code == 2
            )
        if not _validate_driver_projection(projection):
            return False
        if receipt.frame_payload_bytes != (0 if receipt.frame is None else len(receipt.frame._raw)):
            return False
        # A forced Job cleanup may still produce a structurally valid frame,
        # but that call can only support normal source cleanup. The outer
        # caller returns BLOCKED and never asks the wrapper or Root to adjudicate.
        if receipt.forced_termination is True:
            return True
        if receipt.frame is None:
            if (
                receipt.exit_code == 0 and projection["reason"] == "candidate_root_handoff_written"
            ) or projection["receipt_verified"] is True:
                return False
        elif (
            receipt.exit_code != 0
            or projection["reason"] != "candidate_root_handoff_written"
            or projection["receipt_verified"] is not True
            or projection["source_closure_verified"] is not True
            or projection["root_postverify_verified"] is not True
        ):
            return False
        return True
    except Exception:
        return False


def capture_c01_v20_driver_objects(module: ModuleType) -> MappingProxyType:
    """Snapshot this fixed module's source functions and descriptor code.

    Root/V20 callers retain the returned map next to the exact module bytes.
    The map is a snapshot, not authority; every validator still checks the
    module and current object identities against it.
    """

    if (
        type(module) is not ModuleType
        or module.__name__ != MODULE_NAME
        or module.__dict__ is not vars(module)
    ):
        raise RootDriverError("driver_module_binding_invalid")
    result: dict[str, Any] = {}
    for name, value in tuple(module.__dict__.items()):
        if name.startswith("__"):
            continue
        result[name] = value
        if type(value) is FunctionType:
            result[name + ".__code__"] = value.__code__
            result[name + ".__globals__"] = value.__globals__
        elif isinstance(value, type) and value.__module__ == module.__name__:
            for attribute, member in tuple(value.__dict__.items()):
                key = name + "." + attribute
                result[key] = member
                if type(member) is FunctionType:
                    result[key + ".__code__"] = member.__code__
                    result[key + ".__globals__"] = member.__globals__
                elif isinstance(member, (classmethod, staticmethod)):
                    function = member.__func__
                    result[key + ".__func__"] = function
                    result[key + ".__code__"] = function.__code__
                    result[key + ".__globals__"] = function.__globals__
                elif isinstance(member, property):
                    for accessor_name in ("fget", "fset", "fdel"):
                        function = getattr(member, accessor_name)
                        if type(function) is FunctionType:
                            accessor_key = key + "." + accessor_name
                            result[accessor_key] = function
                            result[accessor_key + ".__code__"] = function.__code__
                            result[accessor_key + ".__globals__"] = function.__globals__
    return MappingProxyType(result)


def validate_c01_v20_driver_source_objects(module: ModuleType, objects: Mapping[str, Any]) -> bool:
    """Check the exact driver functions and source object snapshot."""

    try:
        if (
            type(module) is not ModuleType
            or module.__name__ != MODULE_NAME
            or module.__dict__ is not vars(module)
            or type(objects) is not MappingProxyType
        ):
            return False
        current = dict(capture_c01_v20_driver_objects(module))
        return set(current) == set(objects) and all(
            current[name] is objects[name] for name in current
        )
    except Exception:
        return False


class C01V20OuterCloseReceipt:
    """Parent-local same-call closure record after normal CUv2 teardown."""

    __slots__ = (
        "parent_process_receipt",
        "call_nonce",
        "public_source_pins",
        "software_source_pins",
        "source_modules",
        "source_objects",
        "source_pins",
        "held_source_bytes",
        "module_source_pins",
        "module_held_source_bytes",
        "held_software_bytes",
        "source_lease",
        "outer_postverify_verified",
        "normal_close_verified",
        "source_postclose_pins_verified",
        "retained_reference_count",
        "observed_held_public_count",
        "observed_held_software_count",
        "observed_held_count",
        "outer_exit_code",
        "outer_job_empty",
        "stdout_eof",
        "stderr_eof",
        "stderr_empty",
        "frame_eof",
        "job_handles_closed",
        "reader_threads_joined",
        "cleanup_verified",
        "_public_pin_items",
        "_software_pin_items",
        "_factory",
    )

    def __init__(self, *, values: dict[str, Any], _factory: Any = None) -> None:
        if _factory is not _OUTER_CLOSE_FACTORY or type(values) is not dict:
            raise RootDriverError("outer_close_receipt_factory_required")
        expected = {
            "parent_process_receipt",
            "call_nonce",
            "public_source_pins",
            "software_source_pins",
            "source_modules",
            "source_objects",
            "source_pins",
            "held_source_bytes",
            "held_software_bytes",
            "source_lease",
        }
        if set(values) != expected:
            raise RootDriverError("outer_close_receipt_shape_invalid")
        public_pins = _validate_pin_mapping(values["public_source_pins"])
        software_pins = _validate_pin_mapping(values["software_source_pins"])
        if set(public_pins) & set(software_pins):
            raise RootDriverError("outer_close_pin_overlap")
        object_values = dict(values)
        public_proxy = _immutable_pin_mapping(values["public_source_pins"], public_pins)
        software_proxy = _immutable_pin_mapping(values["software_source_pins"], software_pins)
        if _validate_pin_mapping(values["source_pins"]) != public_pins:
            raise RootDriverError("outer_close_source_pin_binding_invalid")
        object_values["public_source_pins"] = public_proxy
        object_values["software_source_pins"] = software_proxy
        object_values["source_pins"] = public_proxy
        object_values["source_modules"] = _immutable_module_mapping(values["source_modules"])
        object_values["source_objects"] = _immutable_object_mapping(values["source_objects"])
        object_values["held_source_bytes"] = _immutable_byte_mapping(values["held_source_bytes"])
        module_paths = set(object_values["source_modules"])
        if (
            module_paths != set(object_values["source_objects"])
            or not module_paths.issubset(public_proxy)
            or not module_paths.issubset(object_values["held_source_bytes"])
        ):
            raise RootDriverError("outer_close_module_map_invalid")
        object_values["module_source_pins"] = MappingProxyType(
            {path: public_proxy[path] for path in sorted(module_paths)}
        )
        object_values["module_held_source_bytes"] = MappingProxyType(
            {path: object_values["held_source_bytes"][path] for path in sorted(module_paths)}
        )
        object_values["held_software_bytes"] = _immutable_byte_mapping(
            values["held_software_bytes"]
        )
        process = values["parent_process_receipt"]
        object_values.update(
            {
                "outer_postverify_verified": True,
                "normal_close_verified": True,
                "source_postclose_pins_verified": True,
                "retained_reference_count": len(_OUTER_KEEPALIVE),
                "observed_held_public_count": len(public_pins),
                "observed_held_software_count": len(software_pins),
                "observed_held_count": len(public_pins) + len(software_pins),
                "outer_exit_code": process.exit_code,
                "outer_job_empty": process.job_empty,
                "stdout_eof": process.stdout_eof,
                "stderr_eof": process.stderr_eof,
                "stderr_empty": process.stderr_raw == b"",
                "frame_eof": process.frame_eof,
                "job_handles_closed": process.job_handles_closed,
                "reader_threads_joined": process.reader_threads_joined,
                "cleanup_verified": validate_c01_v20_parent_process_receipt(process) is True,
            }
        )
        object_values["_public_pin_items"] = tuple(sorted(public_pins.items()))
        object_values["_software_pin_items"] = tuple(sorted(software_pins.items()))
        for name, value in object_values.items():
            object.__setattr__(self, name, value)
        object.__setattr__(self, "_factory", _OUTER_CLOSE_FACTORY)
        if validate_c01_v20_outer_close_receipt(self) is not True:
            raise RootDriverError("outer_close_receipt_invalid")

    def __setattr__(self, _name: str, _value: Any) -> None:
        raise AttributeError("C01V20OuterCloseReceipt is immutable")

    def __repr__(self) -> str:
        return "C01V20OuterCloseReceipt(<outer source close verified; identifiers redacted>)"


class C01V20OuterSourceLease:
    """Same-call CUv2 source hold, with its exact generator kept alive.

    Only :func:`enter_c01_v20_outer_source_lease` can construct this type.
    A successful close is minted by directly invoking the captured context
    manager method once, then checking normal generator exhaustion and the
    exact held source bytes. Failed or uncertain close paths stay retained.
    """

    __slots__ = (
        "cuv2_module",
        "cuv2_source_bytes",
        "cuv2_function",
        "cuv2_function_code",
        "cuv2_function_globals",
        "cuv2_generator_function",
        "cuv2_generator_code",
        "cuv2_generator_globals",
        "manager",
        "manager_type",
        "manager_enter",
        "manager_enter_code",
        "manager_enter_globals",
        "manager_exit",
        "manager_exit_code",
        "manager_exit_globals",
        "generator",
        "held_tuple",
        "held_raw_by_absolute_path",
        "public_source_pins",
        "software_source_pins",
        "source_root",
        "owner_thread_id",
        "source_modules",
        "source_objects",
        "source_pins",
        "held_source_bytes",
        "held_software_bytes",
        "parent_process_receipt",
        "state",
        "exit_started",
        "activation_started",
        "activation_nonce",
        "supervisor_started",
        "credential_free_gate_started",
        "credential_free_gate_nonce",
        "credential_free_gate_supervisor_started",
        "close_result",
        "keepalive_ref",
        "keepalive_container_ref",
        "_factory",
    )

    def __init__(self, *, values: dict[str, Any], _factory: Any = None) -> None:
        if _factory is not _OUTER_LEASE_FACTORY or type(values) is not dict:
            raise RootDriverError("outer_source_lease_factory_required")
        for name, value in values.items():
            object.__setattr__(self, name, value)
        object.__setattr__(self, "_factory", _OUTER_LEASE_FACTORY)

    def __setattr__(self, _name: str, _value: Any) -> None:
        raise AttributeError("C01V20OuterSourceLease is immutable")

    def __repr__(self) -> str:
        return "C01V20OuterSourceLease(<same-call source hold; paths and bytes redacted>)"


def enter_c01_v20_outer_source_lease(
    *,
    cuv2_module: ModuleType,
    cuv2_source_bytes: bytes,
    public_source_pins: Mapping[str, str],
    software_source_pins: Mapping[str, str],
) -> C01V20OuterSourceLease:
    """Enter the pinned CUv2 hold and retain its exact context manager.

    The caller must have loaded ``cuv2_module`` by compiling the exact bytes
    obtained from the same pinned source hold. This function binds that source,
    enters the fixed ``held_public_sources`` generator exactly once, and keeps
    every yielded object alive. It accepts no booleans or caller-built receipt.
    """

    public = _validate_pin_mapping(public_source_pins)
    software = _validate_pin_mapping(software_source_pins)
    if (
        set(public) & set(software)
        or software.get(CUV2_SOURCE_PATH) != CUV2_SOURCE_SHA256
        or type(cuv2_module) is not ModuleType
        or type(cuv2_source_bytes) is not bytes
        or len(cuv2_source_bytes) != CUV2_SOURCE_BYTES
        or hashlib.sha256(cuv2_source_bytes).hexdigest() != CUV2_SOURCE_SHA256
        or cuv2_module.__dict__ is not vars(cuv2_module)
        or cuv2_module.__dict__.get("__file__") != CUV2_SOURCE_PATH
        or cuv2_module.__dict__.get("__c01_source_sha256__") != CUV2_SOURCE_SHA256
    ):
        raise RootDriverError("cuv2_source_binding_invalid")
    held_fn = cuv2_module.__dict__.get("held_public_sources")
    generator_fn = getattr(held_fn, "__wrapped__", None)
    if (
        type(held_fn) is not FunctionType
        or type(generator_fn) is not FunctionType
        or cuv2_module.__dict__.get("held_public_sources") is not held_fn
        or generator_fn.__globals__ is not cuv2_module.__dict__
        or generator_fn.__code__.co_filename != CUV2_SOURCE_PATH
    ):
        raise RootDriverError("cuv2_function_binding_invalid")

    public_proxy = MappingProxyType(dict(public))
    software_proxy = MappingProxyType(dict(software))
    try:
        manager = held_fn(public_proxy, software_proxy)
    except Exception:
        raise RootDriverError("cuv2_manager_create_failed") from None
    manager_type = type(manager)
    enter_fn = getattr(manager_type, "__dict__", {}).get("__enter__")
    exit_fn = getattr(manager_type, "__dict__", {}).get("__exit__")
    manager_doc = generator_fn.__doc__ or manager_type.__doc__
    if (
        manager_type.__module__ != "contextlib"
        or manager_type.__name__ != "_GeneratorContextManager"
        or type(enter_fn) is not FunctionType
        or type(exit_fn) is not FunctionType
        or type(getattr(manager, "__dict__", None)) is not dict
        or set(manager.__dict__) != {"func", "args", "kwds", "gen", "__doc__"}
        or manager.__dict__.get("func") is not generator_fn
        or type(manager.__dict__.get("args")) is not tuple
        or len(manager.__dict__["args"]) != 2
        or manager.__dict__["args"][0] is not public_proxy
        or manager.__dict__["args"][1] is not software_proxy
        or manager.__dict__.get("kwds") != {}
        or manager.__dict__.get("__doc__") is not manager_doc
    ):
        _retain_uncertain_outer_manager(manager, None)
        raise RootDriverError("cuv2_manager_binding_invalid")

    expected_paths = _expected_absolute_source_paths(public, software)
    keepalive = (
        manager,
        cuv2_module,
        cuv2_source_bytes,
        public_proxy,
        software_proxy,
    )
    try:
        _OUTER_KEEPALIVE.append(keepalive)
    except Exception:
        _retain_uncertain_outer_manager(manager, keepalive)
        raise RootDriverError("cuv2_manager_retention_failed") from None

    owner_thread = threading.get_ident()
    try:
        held_tuple = enter_fn(manager)
    except Exception:
        # __enter__ may have acquired only some handles. Keep the exact manager
        # and do not call __exit__ for a context manager that never yielded.
        raise RootDriverError("cuv2_manager_enter_uncertain") from None
    generator = manager.__dict__.get("gen")
    raw_map = held_tuple[2] if type(held_tuple) is tuple and len(held_tuple) == 3 else None
    normalized_raw = _normalize_held_raw_map(raw_map)
    try:
        if type(held_tuple) is not tuple or len(held_tuple) != 3:
            raise RootDriverError("cuv2_held_tuple_invalid")
        if (
            type(held_tuple[0]) is not ModuleType
            or held_tuple[0].__name__ != "_root_public_custody_private"
            or type(held_tuple[1]) is not ModuleType
            or held_tuple[1].__name__ != "_root_public_custody_cli"
        ):
            raise RootDriverError("cuv2_held_module_alias_invalid")
        if type(raw_map) is not dict or set(normalized_raw) != set(expected_paths):
            raise RootDriverError("cuv2_held_path_set_invalid")
        if any(
            hashlib.sha256(raw).hexdigest() != expected_paths[path]
            for path, raw in normalized_raw.items()
        ):
            raise RootDriverError("cuv2_held_digest_invalid")
        if (
            type(generator) is not GeneratorType
            or generator.gi_code is not generator_fn.__code__
            or generator.gi_frame is None
            or generator.gi_frame.f_globals is not cuv2_module.__dict__
            or generator.gi_running is not False
        ):
            raise RootDriverError("cuv2_generator_identity_invalid")
    except Exception as exc:
        if isinstance(exc, RootDriverError):
            raise
        raise RootDriverError("cuv2_held_rows_invalid") from None

    return C01V20OuterSourceLease(
        values={
            "cuv2_module": cuv2_module,
            "cuv2_source_bytes": cuv2_source_bytes,
            "cuv2_function": held_fn,
            "cuv2_function_code": held_fn.__code__,
            "cuv2_function_globals": held_fn.__globals__,
            "cuv2_generator_function": generator_fn,
            "cuv2_generator_code": generator_fn.__code__,
            "cuv2_generator_globals": generator_fn.__globals__,
            "manager": manager,
            "manager_type": manager_type,
            "manager_enter": enter_fn,
            "manager_enter_code": enter_fn.__code__,
            "manager_enter_globals": enter_fn.__globals__,
            "manager_exit": exit_fn,
            "manager_exit_code": exit_fn.__code__,
            "manager_exit_globals": exit_fn.__globals__,
            "generator": generator,
            "held_tuple": held_tuple,
            "held_raw_by_absolute_path": MappingProxyType(dict(normalized_raw)),
            "public_source_pins": public_proxy,
            "software_source_pins": software_proxy,
            "source_root": _source_root_for_driver(),
            "owner_thread_id": owner_thread,
            "source_modules": None,
            "source_objects": None,
            "source_pins": None,
            "held_source_bytes": None,
            "held_software_bytes": None,
            "parent_process_receipt": None,
            "state": "entered",
            "exit_started": False,
            "activation_started": False,
            "activation_nonce": None,
            "supervisor_started": False,
            "credential_free_gate_started": False,
            "credential_free_gate_nonce": None,
            "credential_free_gate_supervisor_started": False,
            "close_result": None,
            "keepalive_ref": keepalive,
            "keepalive_container_ref": _OUTER_KEEPALIVE,
        },
        _factory=_OUTER_LEASE_FACTORY,
    )


def bind_c01_v20_outer_source_modules(
    lease: C01V20OuterSourceLease,
    *,
    source_modules: Mapping[str, ModuleType],
    source_objects: Mapping[str, Mapping[str, Any]],
    source_pins: Mapping[str, str],
    held_source_bytes: Mapping[str, bytes],
) -> None:
    """Bind modules compiled from the exact public bytes returned by CUv2."""

    if not _outer_lease_current(lease, require_entered=True):
        raise RootDriverError("outer_source_lease_invalid")
    public_bytes: dict[str, bytes] = {}
    software_bytes: dict[str, bytes] = {}
    raw_map = lease.held_raw_by_absolute_path
    for relative, digest in lease.public_source_pins.items():
        absolute = _absolute_public_path(lease.source_root, relative)
        raw = raw_map.get(absolute)
        if type(raw) is not bytes or hashlib.sha256(raw).hexdigest() != digest:
            raise RootDriverError("outer_public_source_bytes_invalid")
        public_bytes[relative] = raw
    for absolute, digest in lease.software_source_pins.items():
        normalized = _normalize_absolute_path(absolute)
        raw = raw_map.get(normalized)
        if type(raw) is not bytes or hashlib.sha256(raw).hexdigest() != digest:
            raise RootDriverError("outer_software_source_bytes_invalid")
        software_bytes[absolute] = raw
    if (
        type(source_pins) not in (dict, MappingProxyType)
        or _validate_pin_mapping(source_pins) != dict(lease.public_source_pins)
        or type(held_source_bytes) not in (dict, MappingProxyType)
        or set(held_source_bytes) != set(lease.public_source_pins)
        or any(held_source_bytes[path] is not raw for path, raw in public_bytes.items())
        or lease.source_modules is not None
    ):
        raise RootDriverError("outer_held_source_map_invalid")
    module_proxy = _immutable_module_mapping(source_modules)
    object_proxy = _immutable_object_mapping(source_objects)
    if (
        set(module_proxy) != set(object_proxy)
        or not set(module_proxy).issubset(public_bytes)
        or not _validate_source_module_snapshots(
            module_proxy, object_proxy, lease.public_source_pins, public_bytes
        )
    ):
        raise RootDriverError("outer_source_module_map_invalid")
    object.__setattr__(lease, "source_modules", module_proxy)
    object.__setattr__(lease, "source_objects", object_proxy)
    object.__setattr__(lease, "source_pins", lease.public_source_pins)
    object.__setattr__(lease, "held_source_bytes", MappingProxyType(public_bytes))
    object.__setattr__(lease, "held_software_bytes", MappingProxyType(software_bytes))


def create_c01_v20_outer_close_receipt(
    *,
    lease: C01V20OuterSourceLease,
    parent_process_receipt: C01V20ParentProcessReceipt,
) -> C01V20OuterCloseReceipt:
    """Close the one entered CUv2 manager and mint evidence from that call.

    The exact class-level ``__exit__`` captured at entry is called directly,
    with no caller-provided success flags. A normal return of ``False`` and a
    fully exhausted CUv2 generator prove its post-yield verification path ran.
    Any exception or changed state leaves the source tuple retained.
    """

    if (
        not _outer_lease_current(lease, require_entered=True)
        or validate_c01_v20_parent_process_receipt(parent_process_receipt) is not True
        or lease.source_modules is None
        or lease.source_objects is None
        or lease.source_pins is not lease.public_source_pins
        or lease.held_source_bytes is None
        or lease.held_software_bytes is None
    ):
        raise RootDriverError("outer_source_close_precondition_failed")

    # Mark before invoking foreign cleanup code. If it raises or leaves the
    # generator alive, this lease cannot be retried or converted to success.
    object.__setattr__(lease, "exit_started", True)
    object.__setattr__(lease, "state", "closing")
    object.__setattr__(lease, "parent_process_receipt", parent_process_receipt)
    if not _outer_lease_current(lease, require_entered=False, closing=True):
        object.__setattr__(lease, "state", "uncertain")
        raise RootDriverError("outer_source_close_binding_changed")
    try:
        close_result = lease.manager_exit(lease.manager, None, None, None)
    except Exception:
        object.__setattr__(lease, "state", "uncertain")
        raise RootDriverError("outer_source_close_uncertain") from None
    object.__setattr__(lease, "close_result", close_result)
    generator = lease.generator
    if (
        close_result is not False
        or type(generator) is not GeneratorType
        or generator.gi_frame is not None
        or generator.gi_running is not False
        or not _outer_lease_current(lease, require_entered=False, closing=True)
        or not _outer_bytes_match_lease(lease)
    ):
        object.__setattr__(lease, "state", "uncertain")
        raise RootDriverError("outer_source_postverify_failed")

    # Remove only this lease's exact keepalive tuple. Never clear unrelated
    # retained source or process references.
    keepalive = lease.keepalive_container_ref
    if (
        type(keepalive) is not list
        or _OUTER_KEEPALIVE is not keepalive
        or sum(value is lease.keepalive_ref for value in keepalive) != 1
    ):
        object.__setattr__(lease, "state", "uncertain")
        raise RootDriverError("outer_source_keepalive_changed")
    keepalive.remove(lease.keepalive_ref)
    if (
        type(keepalive) is not list
        or _OUTER_KEEPALIVE is not keepalive
        or any(value is lease.keepalive_ref for value in keepalive)
        or keepalive
    ):
        # This operation removed only the exact tuple for this lease. Other
        # outstanding leases remain untouched and prevent a clean receipt.
        object.__setattr__(lease, "state", "closed_with_other_retained_refs")
        raise RootDriverError("outer_source_retained_references")
    object.__setattr__(lease, "state", "closed")

    receipt = C01V20OuterCloseReceipt(
        values={
            "parent_process_receipt": parent_process_receipt,
            "call_nonce": parent_process_receipt.call_nonce,
            "public_source_pins": lease.public_source_pins,
            "software_source_pins": lease.software_source_pins,
            "source_modules": lease.source_modules,
            "source_objects": lease.source_objects,
            "source_pins": lease.source_pins,
            "held_source_bytes": lease.held_source_bytes,
            "held_software_bytes": lease.held_software_bytes,
            "source_lease": lease,
        },
        _factory=_OUTER_CLOSE_FACTORY,
    )
    return receipt


def _validate_outer_close_receipt(
    receipt: Any, *, require_empty_outer_keepalive: bool
) -> bool:
    """Recheck exact close evidence, optionally allowing a later active lease."""

    try:
        if (
            type(receipt) is not C01V20OuterCloseReceipt
            or receipt._factory is not _OUTER_CLOSE_FACTORY
            or validate_c01_v20_parent_process_receipt(receipt.parent_process_receipt) is not True
            or type(receipt.call_nonce) is not object
            or receipt.call_nonce is not receipt.parent_process_receipt.call_nonce
            or type(receipt.public_source_pins) is not MappingProxyType
            or type(receipt.software_source_pins) is not MappingProxyType
            or type(receipt.source_modules) is not MappingProxyType
            or type(receipt.source_objects) is not MappingProxyType
            or type(receipt.source_pins) is not MappingProxyType
            or type(receipt.held_source_bytes) is not MappingProxyType
            or type(receipt.module_source_pins) is not MappingProxyType
            or type(receipt.module_held_source_bytes) is not MappingProxyType
            or type(receipt.held_software_bytes) is not MappingProxyType
            or receipt.source_pins is not receipt.public_source_pins
            or set(receipt.held_source_bytes) != set(receipt.public_source_pins)
            or set(receipt.held_software_bytes) != set(receipt.software_source_pins)
            or type(receipt.source_lease) is not C01V20OuterSourceLease
            or receipt.source_lease._factory is not _OUTER_LEASE_FACTORY
            or receipt.source_lease.state != "closed"
            or receipt.source_lease.exit_started is not True
            or receipt.source_lease.close_result is not False
            or receipt.source_lease.manager_exit
            is not receipt.source_lease.manager_type.__dict__.get("__exit__")
            or receipt.source_lease.parent_process_receipt is not receipt.parent_process_receipt
            or receipt.source_lease.public_source_pins is not receipt.public_source_pins
            or receipt.source_lease.software_source_pins is not receipt.software_source_pins
            or receipt.source_lease.source_modules is not receipt.source_modules
            or receipt.source_lease.source_objects is not receipt.source_objects
            or receipt.source_lease.source_pins is not receipt.source_pins
            or receipt.source_lease.held_source_bytes is not receipt.held_source_bytes
            or receipt.source_lease.held_software_bytes is not receipt.held_software_bytes
            or not _outer_lease_current(
                receipt.source_lease,
                require_entered=False,
                closed=True,
                allow_other_keepalive_refs=not require_empty_outer_keepalive,
            )
            or set(receipt.source_modules) != set(receipt.source_objects)
            or not set(receipt.source_modules).issubset(receipt.public_source_pins)
            or not set(receipt.source_modules).issubset(receipt.held_source_bytes)
            or set(receipt.module_source_pins) != set(receipt.source_modules)
            or set(receipt.module_held_source_bytes) != set(receipt.source_modules)
            or any(
                receipt.module_source_pins[path] != receipt.public_source_pins[path]
                or receipt.module_held_source_bytes[path] is not receipt.held_source_bytes[path]
                for path in receipt.source_modules
            )
            or receipt._public_pin_items != tuple(sorted(receipt.public_source_pins.items()))
            or receipt._software_pin_items != tuple(sorted(receipt.software_source_pins.items()))
            or any(
                type(raw) is not bytes
                or hashlib.sha256(raw).hexdigest() != receipt.public_source_pins[path]
                for path, raw in receipt.held_source_bytes.items()
            )
            or any(
                type(raw) is not bytes
                or hashlib.sha256(raw).hexdigest() != receipt.software_source_pins[path]
                for path, raw in receipt.held_software_bytes.items()
            )
            or not _validate_source_module_snapshots(
                receipt.source_modules,
                receipt.source_objects,
                receipt.public_source_pins,
                receipt.held_source_bytes,
            )
            or set(receipt.public_source_pins) & set(receipt.software_source_pins)
            or any(
                _validate_pin_mapping(mapping) != dict(mapping)
                for mapping in (receipt.public_source_pins, receipt.software_source_pins)
            )
            or any(
                getattr(receipt, field) is not True
                for field in (
                    "outer_postverify_verified",
                    "normal_close_verified",
                    "source_postclose_pins_verified",
                    "outer_job_empty",
                    "stdout_eof",
                    "stderr_eof",
                    "stderr_empty",
                    "frame_eof",
                    "job_handles_closed",
                    "reader_threads_joined",
                    "cleanup_verified",
                )
            )
            or type(receipt.retained_reference_count) is not int
            or receipt.retained_reference_count != 0
            or type(_OUTER_KEEPALIVE) is not list
            or (require_empty_outer_keepalive and len(_OUTER_KEEPALIVE) != 0)
            or any(value is receipt.source_lease.keepalive_ref for value in _OUTER_KEEPALIVE)
            or type(receipt.observed_held_public_count) is not int
            or receipt.observed_held_public_count != len(receipt.public_source_pins)
            or type(receipt.observed_held_software_count) is not int
            or receipt.observed_held_software_count != len(receipt.software_source_pins)
            or type(receipt.observed_held_count) is not int
            or receipt.observed_held_count
            != len(receipt.public_source_pins) + len(receipt.software_source_pins)
            or type(receipt.outer_exit_code) is not int
            or receipt.outer_exit_code < 0
            or receipt.outer_exit_code != receipt.parent_process_receipt.exit_code
        ):
            return False
        return True
    except Exception:
        return False


def validate_c01_v20_outer_close_receipt(receipt: Any) -> bool:
    """Recheck a newly closed call with no other source lease retained."""

    return _validate_outer_close_receipt(receipt, require_empty_outer_keepalive=True)


def _make_credential_free_gate_receipt(
    process: C01V20ParentProcessReceipt, outer_close: C01V20OuterCloseReceipt
) -> C01V20CredentialFreeGateReceipt:
    if (
        validate_c01_v20_parent_process_receipt(process) is not True
        or validate_c01_v20_outer_close_receipt(outer_close) is not True
        or outer_close.parent_process_receipt is not process
        or process.frame is not None
        or process.frame_payload_bytes != 0
    ):
        raise RootDriverError("credential_free_gate_receipt_inputs_invalid")
    projection = _parse_canonical_projection(process.stdout_raw)
    if not _validate_credential_free_gate_projection(projection):
        raise RootDriverError("credential_free_gate_projection_invalid")
    clean = (
        process.forced_termination is False
        and process.exit_code == 0
        and projection["status"] == "PASS"
        and outer_close.outer_postverify_verified is True
        and outer_close.normal_close_verified is True
        and outer_close.cleanup_verified is True
        and outer_close.retained_reference_count == 0
        and outer_close.outer_job_empty is True
        and outer_close.stdout_eof is True
        and outer_close.stderr_eof is True
        and outer_close.stderr_empty is True
        and outer_close.frame_eof is True
        and outer_close.job_handles_closed is True
        and outer_close.reader_threads_joined is True
        and outer_close.observed_held_count
        == len(outer_close.public_source_pins) + len(outer_close.software_source_pins)
    )
    status = "PASS" if clean else "BLOCKED"
    reason = (
        projection["reason"]
        if status == "PASS" or projection["status"] == "BLOCKED"
        else "credential_free_gate_blocked"
    )
    return C01V20CredentialFreeGateReceipt(
        values={
            "status": status,
            "reason": reason,
            "os_profile_matches": projection["os_profile_matches"],
            "environment_allowlist_verified": projection["environment_allowlist_verified"],
            "credential_names_absent": projection["credential_names_absent"],
            "frame_payload_bytes": 0,
            "writes": 0,
            "formal_c01_pass": False,
            "official_c01_pass_count": 0,
            "forced_cleanup": process.forced_termination,
            "outer_postverify_verified": outer_close.outer_postverify_verified,
            "outer_close_verified": outer_close.normal_close_verified,
            "cleanup_verified": outer_close.cleanup_verified,
            "outer_job_empty": outer_close.outer_job_empty,
            "stdout_eof": outer_close.stdout_eof,
            "stderr_eof": outer_close.stderr_eof,
            "stderr_empty": outer_close.stderr_empty,
            "frame_eof": outer_close.frame_eof,
            "job_handles_closed": outer_close.job_handles_closed,
            "reader_threads_joined": outer_close.reader_threads_joined,
            "exit_code": process.exit_code,
            "_process_receipt": process,
            "_outer_close_receipt": outer_close,
        },
        _factory=_GATE_RECEIPT_FACTORY,
    )


def validate_c01_v20_credential_free_gate_receipt(receipt: Any) -> bool:
    """Recheck a finite host-gate result against its actual process/close receipts."""

    try:
        if (
            type(receipt) is not C01V20CredentialFreeGateReceipt
            or receipt._factory is not _GATE_RECEIPT_FACTORY
            or validate_c01_v20_parent_process_receipt(receipt._process_receipt) is not True
            or _validate_outer_close_receipt(
                receipt._outer_close_receipt, require_empty_outer_keepalive=False
            )
            is not True
            or receipt._outer_close_receipt.parent_process_receipt is not receipt._process_receipt
            or receipt._process_receipt.frame is not None
            or receipt._process_receipt.frame_payload_bytes != 0
            or type(receipt.status) is not str
            or receipt.status not in {"PASS", "BLOCKED"}
            or type(receipt.reason) is not str
            or receipt.reason
            not in {
                "credential_free_gate_verified",
                "user_profile_mismatch",
                "fixed_environment_mismatch",
                "known_folder_unavailable",
                "credential_free_gate_blocked",
            }
            or any(
                type(getattr(receipt, name)) is not bool
                for name in (
                    "os_profile_matches",
                    "environment_allowlist_verified",
                    "credential_names_absent",
                    "formal_c01_pass",
                    "forced_cleanup",
                    "outer_postverify_verified",
                    "outer_close_verified",
                    "cleanup_verified",
                    "outer_job_empty",
                    "stdout_eof",
                    "stderr_eof",
                    "stderr_empty",
                    "frame_eof",
                    "job_handles_closed",
                    "reader_threads_joined",
                )
            )
            or receipt.formal_c01_pass is not False
            or receipt.writes != 0
            or type(receipt.writes) is not int
            or receipt.official_c01_pass_count != 0
            or type(receipt.official_c01_pass_count) is not int
            or receipt.frame_payload_bytes != 0
            or type(receipt.frame_payload_bytes) is not int
            or type(receipt.exit_code) is not int
            or receipt.exit_code != receipt._process_receipt.exit_code
            or receipt.forced_cleanup != receipt._process_receipt.forced_termination
            or receipt.outer_postverify_verified
            != receipt._outer_close_receipt.outer_postverify_verified
            or receipt.outer_close_verified != receipt._outer_close_receipt.normal_close_verified
            or receipt.cleanup_verified != receipt._outer_close_receipt.cleanup_verified
            or receipt.outer_job_empty != receipt._outer_close_receipt.outer_job_empty
            or receipt.stdout_eof != receipt._outer_close_receipt.stdout_eof
            or receipt.stderr_eof != receipt._outer_close_receipt.stderr_eof
            or receipt.stderr_empty != receipt._outer_close_receipt.stderr_empty
            or receipt.frame_eof != receipt._outer_close_receipt.frame_eof
            or receipt.job_handles_closed != receipt._outer_close_receipt.job_handles_closed
            or receipt.reader_threads_joined
            != receipt._outer_close_receipt.reader_threads_joined
        ):
            return False
        projection = _parse_canonical_projection(receipt._process_receipt.stdout_raw)
        if not _validate_credential_free_gate_projection(projection):
            return False
        if (
            receipt.os_profile_matches is not projection["os_profile_matches"]
            or receipt.environment_allowlist_verified
            is not projection["environment_allowlist_verified"]
            or receipt.credential_names_absent is not projection["credential_names_absent"]
        ):
            return False
        if receipt.status == "PASS":
            return (
                receipt.reason == "credential_free_gate_verified"
                and projection["status"] == "PASS"
                and receipt.forced_cleanup is False
                and receipt.exit_code == 0
                and receipt.os_profile_matches is True
                and receipt.environment_allowlist_verified is True
                and receipt.credential_names_absent is True
                and receipt.outer_postverify_verified is True
                and receipt.outer_close_verified is True
                and receipt.cleanup_verified is True
                and receipt.outer_job_empty is True
                and receipt.stdout_eof is True
                and receipt.stderr_eof is True
                and receipt.stderr_empty is True
                and receipt.frame_eof is True
                and receipt.job_handles_closed is True
                and receipt.reader_threads_joined is True
            )
        if receipt.status != "BLOCKED":
            return False
        if projection["status"] == "BLOCKED":
            return receipt.reason == projection["reason"]
        return (
            projection["status"] == "PASS"
            and receipt.reason == "credential_free_gate_blocked"
            and receipt.forced_cleanup is True
        )
    except Exception:
        return False


def _credential_free_gate_current_for(lease: C01V20OuterSourceLease) -> bool:
    receipt = (
        _CREDENTIAL_FREE_GATE_STATE.get("receipt")
        if type(_CREDENTIAL_FREE_GATE_STATE) is dict
        else None
    )
    try:
        if (
            type(_CREDENTIAL_FREE_GATE_STATE) is not dict
            or set(_CREDENTIAL_FREE_GATE_STATE) != {"used", "receipt"}
            or _CREDENTIAL_FREE_GATE_STATE.get("used") is not True
            or validate_c01_v20_credential_free_gate_receipt(receipt) is not True
            or receipt.status != "PASS"
            or receipt._outer_close_receipt.public_source_pins != lease.public_source_pins
            or receipt._outer_close_receipt.software_source_pins != lease.software_source_pins
            or receipt._outer_close_receipt.source_modules.get(_DRIVER_PATH)
            is not lease.source_modules.get(_DRIVER_PATH)
        ):
            return False
        return True
    except Exception:
        return False


def run_root_credential_free_job_channel_gate(
    lease: C01V20OuterSourceLease,
) -> C01V20CredentialFreeGateReceipt:
    """Run one credential-free fixed Windows Job and pipe/profile gate.

    The route accepts only an entered fixed source lease. It has no argv,
    environment, process, handle, or callback override and cannot mint C01
    authority. A successful result is a prerequisite recorded in this driver
    process before the separate activation entry may proceed.
    """

    if (
        _outer_lease_current(lease, require_entered=True) is not True
        or type(lease.source_modules) is not MappingProxyType
        or type(lease.source_objects) is not MappingProxyType
        or not _validate_source_module_snapshots(
            lease.source_modules,
            lease.source_objects,
            lease.source_pins,
            lease.held_source_bytes,
        )
    ):
        raise RootDriverError("credential_free_gate_source_lease_invalid")
    driver_module = _module_for_lease(lease, _DRIVER_PATH)
    if (
        driver_module.__dict__ is not globals()
        or driver_module.__name__ != MODULE_NAME
        or validate_c01_v20_driver_source_objects(
            driver_module, lease.source_objects[_DRIVER_PATH]
        )
        is not True
    ):
        raise RootDriverError("credential_free_gate_driver_binding_invalid")
    wrapper_module = _module_for_lease(lease, _WRAPPER_PATH)
    _require_captured_function(
        wrapper_module,
        lease.source_objects[_WRAPPER_PATH],
        "invoke_c01_v20_credential_free_gate",
    )
    backend_module = _module_for_lease(lease, _JOB_BACKEND_PATH)
    for name in ("_load_kernel32", "_create_job", "_query_job_active_processes", "_as_handle"):
        _require_captured_function(backend_module, lease.source_objects[_JOB_BACKEND_PATH], name)
    if not _fixed_interpreter_source_bytes_match(lease):
        raise RootDriverError("credential_free_gate_interpreter_pin_invalid")
    call_nonce = object()
    _claim_credential_free_gate(lease, call_nonce)
    api = _create_parent_api(backend_module)
    process = _supervise_fixed_child(
        lease, api, call_nonce, child_mode="credential_free_gate"
    )
    outer_close = create_c01_v20_outer_close_receipt(
        lease=lease, parent_process_receipt=process
    )
    receipt = _make_credential_free_gate_receipt(process, outer_close)
    if receipt.status == "PASS":
        with _CREDENTIAL_FREE_GATE_LOCK:
            if _CREDENTIAL_FREE_GATE_STATE.get("receipt") is not None:
                raise RootDriverError("credential_free_gate_receipt_replayed")
            _CREDENTIAL_FREE_GATE_STATE["receipt"] = receipt
    return receipt


def _fixed_interpreter_source_bytes_match(lease: C01V20OuterSourceLease) -> bool:
    """Check the executable and runtime DLL pins before constructing Win32 APIs."""

    try:
        if (
            type(lease) is not C01V20OuterSourceLease
            or type(lease.software_source_pins) is not MappingProxyType
            or type(lease.held_software_bytes) is not MappingProxyType
        ):
            return False
        expected = {
            _PYTHON_EXE_PATH: _PYTHON_EXE_SHA256,
            _PYTHON_DLL_PATH: _PYTHON_DLL_SHA256,
        }
        for path, digest in expected.items():
            raw = lease.held_software_bytes.get(path)
            if (
                lease.software_source_pins.get(path) != digest
                or type(raw) is not bytes
                or hashlib.sha256(raw).hexdigest() != digest
            ):
                return False
        return True
    except Exception:
        return False


def complete_c01_v20_formal_result(
    *,
    frame: Any,
    parent_process_receipt: C01V20ParentProcessReceipt,
    wrapper_call_receipt: Any,
    outer_close_receipt: C01V20OuterCloseReceipt,
) -> Any:
    """Mint and consume the typed Root proof after verified source close.

    The source module/object/byte maps come only from the exact outer close
    receipt produced by this driver.  Caller supplied flags, counters, or
    dictionaries cannot substitute for any typed receipt in the chain.
    """

    if (
        validate_c01_v20_outer_close_receipt(outer_close_receipt) is not True
        or validate_c01_v20_parent_process_receipt(parent_process_receipt) is not True
        or parent_process_receipt.forced_termination is not False
        or outer_close_receipt.parent_process_receipt is not parent_process_receipt
        or outer_close_receipt.call_nonce is not parent_process_receipt.call_nonce
        or type(outer_close_receipt.source_modules) is not MappingProxyType
        or type(outer_close_receipt.source_objects) is not MappingProxyType
        or type(outer_close_receipt.source_pins) is not MappingProxyType
        or type(outer_close_receipt.held_source_bytes) is not MappingProxyType
        or type(outer_close_receipt.module_source_pins) is not MappingProxyType
        or type(outer_close_receipt.module_held_source_bytes) is not MappingProxyType
        or set(outer_close_receipt.source_modules) != set(outer_close_receipt.source_objects)
        or set(outer_close_receipt.source_pins) != set(outer_close_receipt.held_source_bytes)
        or not set(outer_close_receipt.source_modules).issubset(outer_close_receipt.source_pins)
        or set(outer_close_receipt.module_source_pins) != set(outer_close_receipt.source_modules)
        or set(outer_close_receipt.module_held_source_bytes)
        != set(outer_close_receipt.source_modules)
    ):
        raise RootDriverError("formal_completion_outer_close_invalid")

    modules = outer_close_receipt.source_modules
    objects = outer_close_receipt.source_objects
    pins = outer_close_receipt.module_source_pins
    held_bytes = outer_close_receipt.module_held_source_bytes
    required = (
        _ROOT_PATH,
        _WRAPPER_PATH,
        _HANDOFF_PATH,
        _DRIVER_PATH,
        _ADJUDICATOR_PATH,
        _COMPLETION_PATH,
    )
    if any(path not in modules or path not in objects or path not in pins for path in required):
        raise RootDriverError("formal_completion_source_closure_incomplete")
    driver_module = modules[_DRIVER_PATH]
    if (
        type(driver_module) is not ModuleType
        or driver_module.__name__ != MODULE_NAME
        or driver_module.__dict__ is not globals()
        or objects[_DRIVER_PATH].get("complete_c01_v20_formal_result")
        is not complete_c01_v20_formal_result
        or objects[_DRIVER_PATH].get("complete_c01_v20_formal_result.__code__")
        is not complete_c01_v20_formal_result.__code__
        or objects[_DRIVER_PATH].get("complete_c01_v20_formal_result.__globals__") is not globals()
        or not _validate_source_module_snapshots(modules, objects, pins, held_bytes)
    ):
        raise RootDriverError("formal_completion_source_binding_invalid")

    root_module = modules[_ROOT_PATH]
    adjudicator_module = modules[_ADJUDICATOR_PATH]
    completion_module = modules[_COMPLETION_PATH]
    root_objects = objects[_ROOT_PATH]
    adjudicator_objects = objects[_ADJUDICATOR_PATH]
    completion_objects = objects[_COMPLETION_PATH]
    create_invocation = _require_captured_function(
        root_module, root_objects, "create_c01_root_invocation_receipt"
    )
    mint_proof = _require_captured_function(
        adjudicator_module, adjudicator_objects, "mint_c01_root_formal_pass_proof"
    )
    consume_result = _require_captured_function(
        completion_module, completion_objects, "consume_c01_root_formal_pass"
    )
    try:
        invocation_receipt = create_invocation(
            frame,
            parent_process_receipt,
            wrapper_call_receipt,
            outer_close_receipt,
            modules,
            objects,
            pins,
            held_source_bytes=held_bytes,
        )
        proof = mint_proof(
            frame=frame,
            root_invocation_receipt=invocation_receipt,
            wrapper_call_receipt=wrapper_call_receipt,
            outer_close_receipt=outer_close_receipt,
            source_modules=modules,
            source_objects=objects,
            source_pins=pins,
        )
        result = consume_result(
            proof,
            adjudicator_module=adjudicator_module,
            adjudicator_source_objects=adjudicator_objects,
        )
        if (
            type(result) is not completion_module.__dict__.get("C01FormalCompletionResult")
            or result._factory is not completion_module.__dict__.get("_RESULT_FACTORY")
            or type(result.official_c01_pass_count) is not int
            or result.official_c01_pass_count != 1
            or result.formal_c01_pass is not True
        ):
            raise RootDriverError("formal_completion_result_invalid")
        return result
    except RootDriverError:
        raise
    except Exception:
        raise RootDriverError("formal_completion_blocked") from None


def _forced_cleanup_blocked_result(
    outer_close_receipt: C01V20OuterCloseReceipt,
) -> dict[str, Any]:
    """Project only a fully closed forced cleanup; never count it as C01 PASS."""

    if (
        validate_c01_v20_outer_close_receipt(outer_close_receipt) is not True
        or outer_close_receipt.parent_process_receipt.forced_termination is not True
    ):
        raise RootDriverError("forced_cleanup_receipt_invalid")
    return {
        "case_id": CASE_ID,
        "certification": "BLOCKED",
        "mode": PROFILE_ID,
        "profile": PROFILE_ID,
        "reason": "parent_forced_cleanup_completed",
        "write_policy": "NO_WRITE",
        "writes": 0,
        "formal_c01_pass": False,
        "official_c01_pass_count": 0,
        "forced_cleanup": True,
        "request_count": 0,
        "query_callback_count": 0,
        "snapshot_count": 0,
        "write_invocation_count": 0,
        "source_authenticity_verified": False,
        "account_binding_verified": False,
        "source_closure_verified": False,
        "root_postverify_verified": False,
        "outer_postverify_verified": outer_close_receipt.outer_postverify_verified,
        "outer_close_verified": outer_close_receipt.normal_close_verified,
        "cleanup_verified": outer_close_receipt.cleanup_verified,
    }


def _require_captured_function(
    module: ModuleType, objects: Mapping[str, Any], name: str
) -> FunctionType:
    function = module.__dict__.get(name)
    if (
        type(module) is not ModuleType
        or type(objects) is not MappingProxyType
        or type(function) is not FunctionType
        or objects.get(name) is not function
        or objects.get(name + ".__code__") is not function.__code__
        or objects.get(name + ".__globals__") is not function.__globals__
        or function.__globals__ is not module.__dict__
        or function.__module__ != module.__name__
        or function.__qualname__ != name
    ):
        raise RootDriverError("formal_completion_callable_invalid")
    return function


def _validate_pin_mapping(value: Any) -> dict[str, str]:
    if type(value) not in (dict, MappingProxyType) or not 0 < len(value) <= MAX_SOURCE_ROWS:
        raise RootDriverError("source_pin_map_invalid")
    result: dict[str, str] = {}
    for path, pin in value.items():
        if (
            type(path) is not str
            or not path
            or "\\" in path
            or path.startswith("/")
            or any(part in ("", ".", "..") for part in path.split("/"))
            or type(pin) is not str
            or not _SHA256_RE.fullmatch(pin)
        ):
            raise RootDriverError("source_pin_map_invalid")
        result[path] = pin
    return result


def _immutable_pin_mapping(value: Any, parsed: dict[str, str]) -> MappingProxyType:
    if type(value) is MappingProxyType:
        if dict(value) != parsed:
            raise RootDriverError("source_pin_map_changed")
        return value
    return MappingProxyType(dict(parsed))


def _immutable_module_mapping(value: Any) -> MappingProxyType:
    if type(value) not in (dict, MappingProxyType):
        raise RootDriverError("source_module_map_invalid")
    return value if type(value) is MappingProxyType else MappingProxyType(dict(value))


def _immutable_object_mapping(value: Any) -> MappingProxyType:
    if type(value) not in (dict, MappingProxyType):
        raise RootDriverError("source_object_map_invalid")
    copied: dict[str, Mapping[str, Any]] = {}
    for path, rows in value.items():
        if type(rows) not in (dict, MappingProxyType):
            raise RootDriverError("source_object_map_invalid")
        copied[path] = rows if type(rows) is MappingProxyType else MappingProxyType(dict(rows))
    return (
        value
        if type(value) is MappingProxyType
        and all(type(rows) is MappingProxyType for rows in value.values())
        else MappingProxyType(copied)
    )


def _immutable_byte_mapping(value: Any) -> MappingProxyType:
    if type(value) not in (dict, MappingProxyType):
        raise RootDriverError("source_byte_map_invalid")
    if any(type(path) is not str or type(raw) is not bytes for path, raw in value.items()):
        raise RootDriverError("source_byte_map_invalid")
    return value if type(value) is MappingProxyType else MappingProxyType(dict(value))


def _capture_source_module_objects(module: ModuleType) -> MappingProxyType:
    rows: dict[str, Any] = {}
    for name, value in tuple(module.__dict__.items()):
        if name.startswith("__"):
            continue
        rows[name] = value
        if type(value) is FunctionType:
            rows[name + ".__code__"] = value.__code__
            rows[name + ".__globals__"] = value.__globals__
        elif isinstance(value, type) and value.__module__ == module.__name__:
            for attribute, member in tuple(value.__dict__.items()):
                key = name + "." + attribute
                rows[key] = member
                if type(member) is FunctionType:
                    rows[key + ".__code__"] = member.__code__
                    rows[key + ".__globals__"] = member.__globals__
                elif isinstance(member, (classmethod, staticmethod)):
                    function = member.__func__
                    rows[key + ".__func__"] = function
                    rows[key + ".__code__"] = function.__code__
                    rows[key + ".__globals__"] = function.__globals__
                elif isinstance(member, property):
                    for accessor in ("fget", "fset", "fdel"):
                        function = getattr(member, accessor)
                        if type(function) is FunctionType:
                            accessor_key = key + "." + accessor
                            rows[accessor_key] = function
                            rows[accessor_key + ".__code__"] = function.__code__
                            rows[accessor_key + ".__globals__"] = function.__globals__
    return MappingProxyType(rows)


def _validate_source_module_snapshots(
    source_modules: Mapping[str, ModuleType],
    source_objects: Mapping[str, Mapping[str, Any]],
    source_pins: Mapping[str, str],
    held_source_bytes: Mapping[str, bytes],
) -> bool:
    try:
        for path, module in source_modules.items():
            raw = held_source_bytes[path]
            if (
                type(module) is not ModuleType
                or type(path) is not str
                or not path.endswith(".py")
                or module.__dict__ is not vars(module)
                or module.__dict__.get("__c01_source_sha256__") != source_pins[path]
                or hashlib.sha256(raw).hexdigest() != source_pins[path]
                or not _source_path_matches(module.__dict__.get("__file__"), path)
            ):
                return False
            expected = source_objects[path]
            current = _capture_source_module_objects(module)
            if type(expected) is not MappingProxyType or set(expected) != set(current):
                return False
            if any(current[name] is not expected[name] for name in current):
                return False
        return True
    except Exception:
        return False


def _source_root_for_driver() -> str:
    path = os.path.abspath(__file__)
    if os.path.basename(path).casefold() != "iteration41_simnow_c01_v20_root_actual_driver_r3.py":
        raise RootDriverError("driver_path_binding_invalid")
    root = os.path.dirname(os.path.dirname(path))
    if not os.path.isabs(root):
        raise RootDriverError("driver_root_path_invalid")
    return os.path.normcase(os.path.normpath(root))


def _normalize_absolute_path(path: Any) -> str:
    if type(path) is not str or not path or not os.path.isabs(path):
        raise RootDriverError("absolute_source_path_invalid")
    return os.path.normcase(os.path.abspath(os.path.normpath(path)))


def _normalize_held_raw_map(value: Any) -> dict[str, bytes]:
    if type(value) is not dict:
        raise RootDriverError("held_raw_map_invalid")
    result: dict[str, bytes] = {}
    for path, raw in value.items():
        normalized = _normalize_absolute_path(path)
        if normalized in result or type(raw) is not bytes:
            raise RootDriverError("held_raw_map_invalid")
        result[normalized] = raw
    return result


def _absolute_public_path(root: str, relative: str) -> str:
    if type(relative) is not str or not relative or "\\" in relative:
        raise RootDriverError("public_source_path_invalid")
    if any(part in ("", ".", "..") for part in relative.split("/")):
        raise RootDriverError("public_source_path_invalid")
    path = os.path.join(root, *relative.split("/"))
    return _normalize_absolute_path(path)


def _expected_absolute_source_paths(
    public_source_pins: Mapping[str, str], software_source_pins: Mapping[str, str]
) -> dict[str, str]:
    result: dict[str, str] = {}
    root = _source_root_for_driver()
    for relative, digest in public_source_pins.items():
        absolute = _absolute_public_path(root, relative)
        if absolute in result:
            raise RootDriverError("resolved_source_path_overlap")
        result[absolute] = digest
    for path, digest in software_source_pins.items():
        absolute = _normalize_absolute_path(path)
        if absolute in result:
            raise RootDriverError("resolved_source_path_overlap")
        result[absolute] = digest
    if len(result) != len(public_source_pins) + len(software_source_pins):
        raise RootDriverError("resolved_source_path_overlap")
    return result


def _retain_uncertain_outer_manager(manager: Any, keepalive: Any) -> None:
    """Keep an unentered or uncertain exact manager strongly reachable."""

    if type(_OUTER_KEEPALIVE) is list:
        reference = keepalive if type(keepalive) is tuple else (manager,)
        _OUTER_KEEPALIVE.append(reference)


def _outer_bytes_match_lease(lease: C01V20OuterSourceLease) -> bool:
    try:
        expected = _expected_absolute_source_paths(
            lease.public_source_pins, lease.software_source_pins
        )
        raw_map = lease.held_raw_by_absolute_path
        original_map = _normalize_held_raw_map(lease.held_tuple[2])
        if (
            type(raw_map) is not MappingProxyType
            or set(original_map) != set(raw_map)
            or any(original_map[path] is not raw for path, raw in raw_map.items())
            or set(raw_map) != set(expected)
            or type(lease.held_tuple) is not tuple
            or len(lease.held_tuple) != 3
            or type(lease.held_tuple[2]) is not dict
            or any(
                type(path) is not str
                or type(raw) is not bytes
                or hashlib.sha256(raw).hexdigest() != expected[path]
                for path, raw in raw_map.items()
            )
        ):
            return False
        if lease.source_modules is None:
            return lease.held_source_bytes is None and lease.held_software_bytes is None
        if (
            type(lease.source_modules) is not MappingProxyType
            or type(lease.source_objects) is not MappingProxyType
            or lease.source_pins is not lease.public_source_pins
            or type(lease.held_source_bytes) is not MappingProxyType
            or type(lease.held_software_bytes) is not MappingProxyType
            or set(lease.held_source_bytes) != set(lease.public_source_pins)
            or set(lease.held_software_bytes) != set(lease.software_source_pins)
            or any(
                lease.held_source_bytes[relative]
                is not raw_map[_absolute_public_path(lease.source_root, relative)]
                for relative in lease.public_source_pins
            )
            or any(
                lease.held_software_bytes[path] is not raw_map[_normalize_absolute_path(path)]
                for path in lease.software_source_pins
            )
            or not _validate_source_module_snapshots(
                lease.source_modules,
                lease.source_objects,
                lease.public_source_pins,
                lease.held_source_bytes,
            )
        ):
            return False
        return True
    except Exception:
        return False


def _outer_lease_current(
    lease: Any,
    *,
    require_entered: bool,
    closing: bool = False,
    closed: bool = False,
    allow_other_keepalive_refs: bool = False,
) -> bool:
    """Recheck current CUv2 source, generator, context manager, and lease state."""

    try:
        if (
            type(lease) is not C01V20OuterSourceLease
            or lease._factory is not _OUTER_LEASE_FACTORY
            or lease.owner_thread_id != threading.get_ident()
            or type(lease.activation_started) is not bool
            or (lease.activation_started is False and lease.activation_nonce is not None)
            or (lease.activation_started is True and type(lease.activation_nonce) is not object)
            or type(lease.credential_free_gate_started) is not bool
            or (
                lease.credential_free_gate_started is False
                and lease.credential_free_gate_nonce is not None
            )
            or (
                lease.credential_free_gate_started is True
                and type(lease.credential_free_gate_nonce) is not object
            )
            or type(lease.credential_free_gate_supervisor_started) is not bool
            or lease.source_root != _source_root_for_driver()
            or type(lease.cuv2_module) is not ModuleType
            or lease.cuv2_module.__dict__ is not vars(lease.cuv2_module)
            or lease.cuv2_module.__dict__.get("__file__") != CUV2_SOURCE_PATH
            or lease.cuv2_module.__dict__.get("__c01_source_sha256__") != CUV2_SOURCE_SHA256
            or type(lease.cuv2_source_bytes) is not bytes
            or len(lease.cuv2_source_bytes) != CUV2_SOURCE_BYTES
            or hashlib.sha256(lease.cuv2_source_bytes).hexdigest() != CUV2_SOURCE_SHA256
            or lease.cuv2_module.__dict__.get("held_public_sources") is not lease.cuv2_function
            or type(lease.cuv2_function) is not FunctionType
            or lease.cuv2_function.__code__ is not lease.cuv2_function_code
            or lease.cuv2_function.__globals__ is not lease.cuv2_function_globals
            or getattr(lease.cuv2_function, "__wrapped__", None)
            is not lease.cuv2_generator_function
            or type(lease.cuv2_generator_function) is not FunctionType
            or lease.cuv2_generator_function.__code__ is not lease.cuv2_generator_code
            or lease.cuv2_generator_function.__globals__ is not lease.cuv2_generator_globals
            or lease.cuv2_generator_globals is not lease.cuv2_module.__dict__
            or lease.cuv2_generator_code.co_filename != CUV2_SOURCE_PATH
            or type(lease.public_source_pins) is not MappingProxyType
            or type(lease.software_source_pins) is not MappingProxyType
            or set(lease.public_source_pins) & set(lease.software_source_pins)
            or not isinstance(lease.manager_type, type)
            or type(lease.manager) is not lease.manager_type
            or lease.manager_type.__module__ != "contextlib"
            or lease.manager_type.__name__ != "_GeneratorContextManager"
            or lease.manager_type.__dict__.get("__enter__") is not lease.manager_enter
            or lease.manager_type.__dict__.get("__exit__") is not lease.manager_exit
            or type(lease.manager_enter) is not FunctionType
            or lease.manager_enter.__code__ is not lease.manager_enter_code
            or lease.manager_enter.__globals__ is not lease.manager_enter_globals
            or type(lease.manager_exit) is not FunctionType
            or lease.manager_exit.__code__ is not lease.manager_exit_code
            or lease.manager_exit.__globals__ is not lease.manager_exit_globals
            or lease.manager.__dict__.get("gen") is not lease.generator
            or type(lease.generator) is not GeneratorType
            or lease.generator.gi_code is not lease.cuv2_generator_code
            or (
                lease.generator.gi_frame is not None
                and lease.generator.gi_frame.f_globals is not lease.cuv2_module.__dict__
            )
            or lease.generator.gi_running is not False
            or not _outer_bytes_match_lease(lease)
        ):
            return False
        if require_entered:
            if (
                lease.state != "entered"
                or lease.exit_started is not False
                or lease.generator.gi_frame is None
                or type(lease.manager.__dict__) is not dict
                or set(lease.manager.__dict__) != {"gen", "__doc__"}
                or lease.manager.__dict__.get("__doc__")
                is not (lease.cuv2_generator_function.__doc__ or lease.manager_type.__doc__)
            ):
                return False
        elif closing:
            if (
                lease.state != "closing"
                or lease.exit_started is not True
                or type(lease.manager.__dict__) is not dict
                or set(lease.manager.__dict__) != {"gen", "__doc__"}
                or lease.manager.__dict__.get("__doc__")
                is not (lease.cuv2_generator_function.__doc__ or lease.manager_type.__doc__)
            ):
                return False
        elif closed:
            if (
                lease.state != "closed"
                or lease.exit_started is not True
                or lease.close_result is not False
                or lease.generator.gi_frame is not None
                or type(lease.manager.__dict__) is not dict
                or set(lease.manager.__dict__) != {"gen", "__doc__"}
                or lease.manager.__dict__.get("__doc__")
                is not (lease.cuv2_generator_function.__doc__ or lease.manager_type.__doc__)
            ):
                return False
        if not closed:
            keepalive = lease.keepalive_container_ref
            if (
                type(keepalive) is not list
                or _OUTER_KEEPALIVE is not keepalive
                or sum(value is lease.keepalive_ref for value in keepalive) != 1
            ):
                return False
        elif (
            type(lease.keepalive_container_ref) is not list
            or _OUTER_KEEPALIVE is not lease.keepalive_container_ref
            or any(value is lease.keepalive_ref for value in _OUTER_KEEPALIVE)
            or (not allow_other_keepalive_refs and _OUTER_KEEPALIVE)
        ):
            return False
        if lease.source_modules is not None:
            if (
                type(lease.source_modules) is not MappingProxyType
                or type(lease.source_objects) is not MappingProxyType
                or lease.source_pins is not lease.public_source_pins
                or type(lease.held_source_bytes) is not MappingProxyType
                or type(lease.held_software_bytes) is not MappingProxyType
                or not _validate_source_module_snapshots(
                    lease.source_modules,
                    lease.source_objects,
                    lease.public_source_pins,
                    lease.held_source_bytes,
                )
            ):
                return False
        return True
    except Exception:
        return False


def _source_path_matches(value: Any, relative: str) -> bool:
    if type(value) is not str or not value:
        return False
    normalized = value.replace("\\", "/").casefold()
    target = relative.casefold()
    return normalized == target or normalized.endswith("/" + target)


def _validate_driver_projection(value: Any) -> bool:
    if type(value) is not dict or set(value) != _PROJECTION_KEYS:
        return False
    if (
        value.get("case_id") != CASE_ID
        or value.get("certification") != "BLOCKED"
        or value.get("mode") != PROFILE_ID
        or value.get("profile") != PROFILE_ID
        or type(value.get("reason")) is not str
        or not _SAFE_REASON_RE.fullmatch(value["reason"])
        or value.get("write_policy") != "NO_WRITE"
        or type(value.get("writes")) is not int
        or value["writes"] != 0
        or type(value.get("receipt_verified")) is not bool
        or type(value.get("source_closure_verified")) is not bool
        or type(value.get("root_postverify_verified")) is not bool
        or type(value.get("request_count")) is not int
        or type(value.get("query_callback_count")) is not int
        or type(value.get("snapshot_count")) is not int
        or type(value.get("write_invocation_count")) is not int
        or any(
            type(value[key]) is not int or value[key] < 0
            for key in (
                "request_count",
                "query_callback_count",
                "snapshot_count",
                "write_invocation_count",
            )
        )
        or any(value.get(key) is not None for key in _PARENT_PROJECTION_KEYS)
    ):
        return False
    if value["receipt_verified"] is True:
        return (
            value.get("reason") == "candidate_root_handoff_written"
            and value.get("receipt_type") == "C01RootContentCustodyReceipt"
            and value.get("source_closure_verified") is True
            and value.get("root_postverify_verified") is True
            and value.get("request_count") == 8
            and 6 <= value.get("query_callback_count") <= 8
            and value.get("snapshot_count") == 2
            and value.get("write_invocation_count") == 0
        )
    return (
        value.get("receipt_type") is None
        and value.get("source_closure_verified") is False
        and value.get("root_postverify_verified") is False
        and value.get("request_count") == 0
        and value.get("query_callback_count") == 0
        and value.get("snapshot_count") == 0
        and value.get("write_invocation_count") == 0
    )


def _validate_credential_free_gate_projection(value: Any) -> bool:
    """Validate the finite result for the separate host-only gate route."""

    keys = {
        "gate_id",
        "status",
        "reason",
        "os_profile_matches",
        "environment_allowlist_verified",
        "credential_names_absent",
        "frame_payload_bytes",
        "writes",
        "formal_c01_pass",
        "official_c01_pass_count",
    }
    if type(value) is not dict or set(value) != keys:
        return False
    allowed_reasons = {
        "credential_free_gate_verified",
        "user_profile_mismatch",
        "fixed_environment_mismatch",
        "known_folder_unavailable",
        "credential_free_gate_blocked",
    }
    if (
        type(value.get("gate_id")) is not str
        or value["gate_id"] != _GATE_ID
        or type(value.get("status")) is not str
        or value["status"] not in {"PASS", "BLOCKED"}
        or type(value.get("reason")) is not str
        or value["reason"] not in allowed_reasons
        or any(
            type(value.get(name)) is not bool
            for name in (
                "os_profile_matches",
                "environment_allowlist_verified",
                "credential_names_absent",
                "formal_c01_pass",
            )
        )
        or type(value.get("frame_payload_bytes")) is not int
        or value["frame_payload_bytes"] != 0
        or type(value.get("writes")) is not int
        or value["writes"] != 0
        or value["formal_c01_pass"] is not False
        or type(value.get("official_c01_pass_count")) is not int
        or value["official_c01_pass_count"] != 0
    ):
        return False
    if value["status"] == "PASS":
        return (
            value["reason"] == "credential_free_gate_verified"
            and value["os_profile_matches"] is True
            and value["environment_allowlist_verified"] is True
            and value["credential_names_absent"] is True
        )
    if value["reason"] == "credential_free_gate_verified":
        return False
    if value["reason"] == "fixed_environment_mismatch":
        return (
            value["environment_allowlist_verified"] is False
            and value["os_profile_matches"] is False
        )
    if value["reason"] in {"known_folder_unavailable", "user_profile_mismatch"}:
        return (
            value["environment_allowlist_verified"] is True
            and value["credential_names_absent"] is True
            and value["os_profile_matches"] is False
        )
    return True


def _parse_canonical_projection(raw: bytes) -> dict[str, Any]:
    if type(raw) is not bytes or not 0 < len(raw) <= MAX_PUBLIC_PROJECTION_BYTES:
        raise RootDriverError("public_projection_size_invalid")

    def unique_pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("duplicate key")
            result[key] = value
        return result

    try:
        value = json.loads(
            raw.decode("utf-8"),
            object_pairs_hook=unique_pairs,
            parse_constant=lambda _item: (_ for _ in ()).throw(ValueError("constant")),
        )
    except Exception:
        raise RootDriverError("public_projection_invalid") from None
    if type(value) is not dict:
        raise RootDriverError("public_projection_invalid")
    canonical = json.dumps(
        value, ensure_ascii=True, allow_nan=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    if canonical != raw:
        raise RootDriverError("public_projection_noncanonical")
    return value


class _Win32ParentApi:
    """Small fixed Win32 adapter for the parent-owned V20 call.

    The adapter is constructed only by :func:`run_root_activation`. Tests
    replace that factory with a fake object implementing the same methods;
    this class has no subprocess or native-provider fallback.
    """

    __slots__ = (
        "ctypes",
        "wintypes",
        "kernel32",
        "backend",
        "_security_type",
        "_fd_owned_handles",
        "_fd_closed_handles",
        "_fd_streams",
    )

    def __init__(self, backend: ModuleType) -> None:
        if os.name != "nt":
            raise _ParentLaunchError("windows_required")
        try:
            import ctypes
            from ctypes import wintypes

            kernel32_loader = backend.__dict__.get("_load_kernel32")
            if type(kernel32_loader) is not FunctionType:
                raise ValueError
            kernel32 = kernel32_loader()
            self.ctypes = ctypes
            self.wintypes = wintypes
            self.kernel32 = kernel32
            self.backend = backend
            self._fd_owned_handles: set[int] = set()
            self._fd_closed_handles: set[int] = set()
            self._fd_streams: dict[int, Any] = {}

            class _SECURITY_ATTRIBUTES(ctypes.Structure):
                _fields_ = [
                    ("nLength", wintypes.DWORD),
                    ("lpSecurityDescriptor", wintypes.LPVOID),
                    ("bInheritHandle", wintypes.BOOL),
                ]

            self._security_type = _SECURITY_ATTRIBUTES
            self._configure_api()
        except _ParentLaunchError:
            raise
        except Exception:
            raise _ParentLaunchError("win32_parent_api_unavailable") from None

    def _configure_api(self) -> None:
        ctypes = self.ctypes
        wintypes = self.wintypes
        kernel32 = self.kernel32
        kernel32.CreatePipe.argtypes = [
            ctypes.POINTER(wintypes.HANDLE),
            ctypes.POINTER(wintypes.HANDLE),
            ctypes.POINTER(self._security_type),
            wintypes.DWORD,
        ]
        kernel32.CreatePipe.restype = wintypes.BOOL
        kernel32.SetHandleInformation.argtypes = [wintypes.HANDLE, wintypes.DWORD, wintypes.DWORD]
        kernel32.SetHandleInformation.restype = wintypes.BOOL
        kernel32.CreateFileW.argtypes = [
            wintypes.LPCWSTR,
            wintypes.DWORD,
            wintypes.DWORD,
            ctypes.POINTER(self._security_type),
            wintypes.DWORD,
            wintypes.DWORD,
            wintypes.HANDLE,
        ]
        kernel32.CreateFileW.restype = wintypes.HANDLE
        kernel32.InitializeProcThreadAttributeList.argtypes = [
            wintypes.LPVOID,
            wintypes.DWORD,
            wintypes.DWORD,
            ctypes.POINTER(ctypes.c_size_t),
        ]
        kernel32.InitializeProcThreadAttributeList.restype = wintypes.BOOL
        kernel32.UpdateProcThreadAttribute.argtypes = [
            wintypes.LPVOID,
            wintypes.DWORD,
            ctypes.c_size_t,
            wintypes.LPVOID,
            ctypes.c_size_t,
            wintypes.LPVOID,
            ctypes.POINTER(ctypes.c_size_t),
        ]
        kernel32.UpdateProcThreadAttribute.restype = wintypes.BOOL
        kernel32.DeleteProcThreadAttributeList.argtypes = [wintypes.LPVOID]
        kernel32.DeleteProcThreadAttributeList.restype = None
        kernel32.ResumeThread.argtypes = [wintypes.HANDLE]
        kernel32.ResumeThread.restype = wintypes.DWORD
        kernel32.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
        kernel32.WaitForSingleObject.restype = wintypes.DWORD
        kernel32.GetExitCodeProcess.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
        kernel32.GetExitCodeProcess.restype = wintypes.BOOL
        kernel32.TerminateJobObject.argtypes = [wintypes.HANDLE, wintypes.UINT]
        kernel32.TerminateJobObject.restype = wintypes.BOOL
        kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
        kernel32.CloseHandle.restype = wintypes.BOOL
        kernel32.GetWindowsDirectoryW.argtypes = [wintypes.LPWSTR, wintypes.UINT]
        kernel32.GetWindowsDirectoryW.restype = wintypes.UINT

    def _security_attributes(self, *, inheritable: bool):
        value = self._security_type()
        value.nLength = self.ctypes.sizeof(value)
        value.lpSecurityDescriptor = None
        value.bInheritHandle = bool(inheritable)
        return value

    @staticmethod
    def _handle_value(value: Any) -> int:
        raw = getattr(value, "value", value)
        if type(raw) is not int or raw <= 0:
            return 0
        return raw

    def create_pipe(self, state: dict[str, Any]) -> tuple[int, int]:
        if type(state) is not dict:
            raise _ParentLaunchError("parent_pipe_state_invalid")
        read_handle = self.wintypes.HANDLE()
        write_handle = self.wintypes.HANDLE()
        security = self._security_attributes(inheritable=True)
        read_value = self._handle_value(read_handle)
        write_value = self._handle_value(write_handle)
        try:
            created = bool(
                self.kernel32.CreatePipe(
                    self.ctypes.byref(read_handle),
                    self.ctypes.byref(write_handle),
                    self.ctypes.byref(security),
                    0,
                )
            )
        except BaseException:
            state["pipe_setup_uncertain"] = True
            read_value = self._handle_value(read_handle)
            write_value = self._handle_value(write_handle)
            _track_owned_handle(state, read_value)
            _track_owned_handle(state, write_value)
            raise
        read_value = self._handle_value(read_handle)
        write_value = self._handle_value(write_handle)
        _track_owned_handle(state, read_value)
        _track_owned_handle(state, write_value)
        if not created:
            raise _ParentLaunchError("parent_pipe_create_failed")
        if not read_value or not write_value:
            raise _ParentLaunchError("parent_pipe_handle_invalid")
        # Only the child write end may enter its fixed HANDLE_LIST.
        if not self.kernel32.SetHandleInformation(read_value, 1, 0):
            raise _ParentLaunchError("parent_pipe_inherit_flag_failed")
        state.setdefault("pipes", []).append((read_value, write_value))
        return read_value, write_value

    def open_null_input(self, state: dict[str, Any]) -> int:
        if type(state) is not dict:
            raise _ParentLaunchError("parent_stdin_state_invalid")
        security = self._security_attributes(inheritable=True)
        try:
            handle = self.kernel32.CreateFileW(
                "NUL",
                0x80000000,  # GENERIC_READ
                0x00000001 | 0x00000002,  # FILE_SHARE_READ | FILE_SHARE_WRITE
                self.ctypes.byref(security),
                3,  # OPEN_EXISTING
                0x00000080,  # FILE_ATTRIBUTE_NORMAL
                None,
            )
        except BaseException:
            state["stdin_setup_uncertain"] = True
            raise
        result = self._handle_value(handle)
        if not result:
            raise _ParentLaunchError("parent_stdin_handle_invalid")
        _track_owned_handle(state, result)
        return result

    def create_job(self) -> int:
        try:
            create = self.backend.__dict__["_create_job"]
            return create(self.kernel32)
        except Exception:
            raise _ParentLaunchError("parent_job_create_failed") from None

    def create_suspended_process(
        self,
        *,
        job: int,
        inherited_handles: tuple[int, ...],
        stdio_handles: tuple[int, int, int],
        argv: tuple[str, ...],
        cwd: str,
        env: Mapping[str, str],
        state: dict[str, Any],
    ) -> _ParentProcessControls:
        """Create one suspended child atomically in its Job and handle list."""

        ctypes = self.ctypes
        wintypes = self.wintypes
        backend = self.backend
        kernel = self.kernel32
        if (
            type(job) is not int
            or job <= 0
            or type(inherited_handles) is not tuple
            or len(inherited_handles) != 4
            or any(type(handle) is not int or handle <= 0 for handle in inherited_handles)
            or len(set(inherited_handles)) != len(inherited_handles)
            or type(stdio_handles) is not tuple
            or len(stdio_handles) != 3
            or stdio_handles != inherited_handles[:3]
            or type(argv) is not tuple
            or len(argv) < 5
            or argv[0] != _PYTHON_EXE_PATH
            or argv[1:4] != ("-I", "-S", "-B")
            or argv[4] != "-c"
            or type(cwd) is not str
            or cwd.replace("\\", "/").casefold() != _ROOT_DIRECTORY.casefold()
            or type(env) not in (dict, MappingProxyType)
            or type(state) is not dict
        ):
            raise _ParentLaunchError("parent_fixed_command_invalid")

        size = ctypes.c_size_t(0)
        try:
            kernel.InitializeProcThreadAttributeList(None, 2, 0, ctypes.byref(size))
        except Exception:
            pass
        if not size.value:
            raise _ParentLaunchError("parent_attribute_list_size_failed")
        storage = ctypes.create_string_buffer(size.value)
        attribute_list = ctypes.cast(storage, wintypes.LPVOID)
        state["attribute_storage"] = storage
        try:
            initialized = bool(
                kernel.InitializeProcThreadAttributeList(attribute_list, 2, 0, ctypes.byref(size))
            )
        except BaseException:
            state["attribute_list"] = attribute_list
            state["attribute_list_open"] = True
            state["attribute_setup_uncertain"] = True
            raise
        if not initialized:
            state.pop("attribute_storage", None)
            raise _ParentLaunchError("parent_attribute_list_init_failed")
        state["attribute_list"] = attribute_list
        state["attribute_list_open"] = True

        job_array = (wintypes.HANDLE * 1)(wintypes.HANDLE(job))
        handle_array = (wintypes.HANDLE * len(inherited_handles))(
            *(wintypes.HANDLE(handle) for handle in inherited_handles)
        )
        state["job_array"] = job_array
        state["handle_array"] = handle_array
        state["attribute_setup_uncertain"] = False
        try:
            updated_job = bool(
                kernel.UpdateProcThreadAttribute(
                    attribute_list,
                    0,
                    0x0002000D,  # PROC_THREAD_ATTRIBUTE_JOB_LIST
                    ctypes.cast(job_array, wintypes.LPVOID),
                    ctypes.sizeof(job_array),
                    None,
                    None,
                )
            )
            updated_handles = bool(
                kernel.UpdateProcThreadAttribute(
                    attribute_list,
                    0,
                    0x00020002,  # PROC_THREAD_ATTRIBUTE_HANDLE_LIST
                    ctypes.cast(handle_array, wintypes.LPVOID),
                    ctypes.sizeof(handle_array),
                    None,
                    None,
                )
            )
        except BaseException:
            if self.delete_attribute_state(state) is not True:
                state["attribute_setup_uncertain"] = True
            raise
        if not updated_job or not updated_handles:
            if self.delete_attribute_state(state) is not True:
                raise _ParentLaunchError(
                    "parent_process_attributes_cleanup_uncertain", uncertain=True
                )
            raise _ParentLaunchError("parent_process_attributes_failed")

        try:
            command_text = subprocess.list2cmdline(list(argv))
            if len(command_text) >= 32767:
                raise _ParentLaunchError("parent_command_line_too_long")
            command_line = ctypes.create_unicode_buffer(command_text)
            fixed_env = _validate_fixed_environment(self, env)
            env_text = (
                "\0".join(
                    "{}={}".format(key, value)
                    for key, value in sorted(fixed_env.items(), key=lambda item: item[0].casefold())
                )
                + "\0\0"
            )
            environment_block = ctypes.create_unicode_buffer(env_text)
            startup_ex = backend._STARTUPINFOEXW()
            startup_ex.StartupInfo.cb = ctypes.sizeof(startup_ex)
            startup_ex.lpAttributeList = attribute_list
            startup_ex.StartupInfo.dwFlags = 0x00000100  # STARTF_USESTDHANDLES
            startup_ex.StartupInfo.hStdInput = wintypes.HANDLE(stdio_handles[0])
            startup_ex.StartupInfo.hStdOutput = wintypes.HANDLE(stdio_handles[1])
            startup_ex.StartupInfo.hStdError = wintypes.HANDLE(stdio_handles[2])
            process_info = backend._PROCESS_INFORMATION()
        except BaseException:
            if self.delete_attribute_state(state) is not True:
                state["attribute_setup_uncertain"] = True
            raise
        state["process_info"] = process_info
        flags = 0x00000004 | 0x00000400 | 0x00080000 | 0x08000000
        if state.get("process_create_call_count") != 0:
            state["process_creation_uncertain"] = True
            raise _ParentLaunchError("parent_process_creation_replayed", uncertain=True)
        state["process_create_call_count"] = 1
        state["create_attempted"] = True
        try:
            created = bool(
                kernel.CreateProcessW(
                    argv[0],
                    command_line,
                    None,
                    None,
                    True,
                    flags,
                    environment_block,
                    cwd,
                    ctypes.cast(ctypes.byref(startup_ex), ctypes.POINTER(backend._STARTUPINFOW)),
                    ctypes.byref(process_info),
                )
            )
        except BaseException:
            state["process_creation_uncertain"] = True
            raise
        state["process_creation_uncertain"] = False
        controls = _ParentProcessControls(
            job=job,
            process=backend._as_handle(process_info.hProcess),
            thread=backend._as_handle(process_info.hThread),
            pid=int(process_info.dwProcessId),
            tid=int(process_info.dwThreadId),
            attribute_list=attribute_list,
            attribute_storage=storage,
            job_array=job_array,
            handle_array=handle_array,
            created=created,
        )
        return controls

    def delete_attribute_state(self, state: dict[str, Any]) -> bool:
        """Delete an attribute list that has not been transferred to controls."""

        if type(state) is not dict or state.get("attribute_list_open") is not True:
            return False
        attribute_list = state.get("attribute_list")
        if attribute_list is None:
            return False
        try:
            self.kernel32.DeleteProcThreadAttributeList(attribute_list)
        except Exception:
            state["attribute_setup_uncertain"] = True
            return False
        _forget_attribute_state(state)
        return True

    def delete_attributes(self, controls: _ParentProcessControls, state: dict[str, Any]) -> bool:
        if controls.attribute_list is None:
            return True
        try:
            self.kernel32.DeleteProcThreadAttributeList(controls.attribute_list)
            controls.attribute_list = None
            controls.attribute_storage = None
            controls.job_array = None
            controls.handle_array = None
            _forget_attribute_state(state)
            return True
        except Exception:
            state["attribute_setup_uncertain"] = True
            return False

    def open_read_stream(self, handle: int, state: dict[str, Any]):
        if type(state) is not dict or type(handle) is not int or handle <= 0:
            raise _ParentLaunchError("parent_reader_handle_invalid")
        fd = None
        try:
            import msvcrt

            fd = msvcrt.open_osfhandle(handle, os.O_BINARY | os.O_RDONLY)
            self._fd_owned_handles.add(handle)
            state.setdefault("fd_owned_handles", set()).add(handle)
            _owned_handle_set(state).discard(handle)
            state.setdefault("fd_by_handle", {})[handle] = fd
        except BaseException as exc:
            state.setdefault("fd_conversion_uncertain_handles", set()).add(handle)
            if isinstance(exc, Exception):
                raise _ParentLaunchError("parent_reader_handle_conversion_failed") from None
            raise
        try:
            stream = os.fdopen(fd, "rb", buffering=0)
            self._fd_streams[handle] = stream
            state.setdefault("stream_handle_by_id", {})[id(stream)] = handle
            return stream
        except BaseException as exc:
            if fd is not None:
                try:
                    os.close(fd)
                    self._fd_closed_handles.add(handle)
                    state.setdefault("fd_owned_handles", set()).discard(handle)
                    state.setdefault("fd_closed_handles", set()).add(handle)
                    state.setdefault("fd_by_handle", {}).pop(handle, None)
                    _record_handle_closed(state, handle)
                except BaseException:
                    state.setdefault("fd_close_uncertain_handles", set()).add(handle)
                    if isinstance(exc, Exception):
                        raise _ParentLaunchError(
                            "parent_reader_stream_cleanup_uncertain", uncertain=True
                        ) from None
                    raise
            if isinstance(exc, Exception):
                raise _ParentLaunchError("parent_reader_stream_open_failed") from None
            raise

    def resume_thread(self, thread: int) -> bool:
        try:
            return int(self.kernel32.ResumeThread(thread)) != 0xFFFFFFFF
        except Exception:
            return False

    def wait_process(self, process: int, timeout_ms: int) -> str:
        try:
            result = int(self.kernel32.WaitForSingleObject(process, timeout_ms))
        except Exception:
            return "error"
        if result == 0:
            return "signaled"
        if result == 0x00000102:
            return "timeout"
        return "error"

    def get_exit_code(self, process: int) -> int | None:
        value = self.wintypes.DWORD()
        try:
            if not self.kernel32.GetExitCodeProcess(process, self.ctypes.byref(value)):
                return None
            return int(value.value)
        except Exception:
            return None

    def terminate_job(self, job: int) -> bool:
        try:
            return bool(self.kernel32.TerminateJobObject(job, 2))
        except Exception:
            return False

    def query_job_active(self, job: int) -> int | None:
        try:
            query = self.backend.__dict__["_query_job_active_processes"]
            return query(self.kernel32, job)
        except Exception:
            return None

    def close_handle(self, handle: int) -> bool:
        if type(handle) is not int or handle <= 0:
            return False
        try:
            return bool(self.kernel32.CloseHandle(handle))
        except Exception:
            return False

    def windows_directory(self) -> str:
        try:
            buffer = self.ctypes.create_unicode_buffer(32768)
            length = int(self.kernel32.GetWindowsDirectoryW(buffer, len(buffer)))
            value = buffer.value
            if not 0 < length < len(buffer) or not value:
                raise ValueError
            return value.rstrip("\\/")
        except Exception:
            raise _ParentLaunchError("windows_directory_unavailable") from None

    def user_profile_directory(self) -> str:
        """Read the current user's profile through the OS known-folder API.

        The child starts with an explicitly constructed environment, so this
        path must come from Windows rather than an inherited environment value.
        """

        ctypes = self.ctypes
        wintypes = self.wintypes
        profile_buffer = wintypes.LPWSTR()
        ole32 = None
        try:
            shell32 = ctypes.WinDLL("shell32", use_last_error=True)
            ole32 = ctypes.WinDLL("ole32", use_last_error=True)

            class _KNOWN_FOLDER_ID(ctypes.Structure):
                _fields_ = [
                    ("Data1", wintypes.DWORD),
                    ("Data2", wintypes.WORD),
                    ("Data3", wintypes.WORD),
                    ("Data4", wintypes.BYTE * 8),
                ]

            folder_id = _KNOWN_FOLDER_ID(
                0x5E6C858F,
                0x0E22,
                0x4760,
                (wintypes.BYTE * 8)(0x9A, 0xFE, 0xEA, 0x33, 0x17, 0xB6, 0x71, 0x73),
            )
            get_known_folder_path = shell32.SHGetKnownFolderPath
            get_known_folder_path.argtypes = [
                ctypes.POINTER(_KNOWN_FOLDER_ID),
                wintypes.DWORD,
                wintypes.HANDLE,
                ctypes.POINTER(wintypes.LPWSTR),
            ]
            get_known_folder_path.restype = ctypes.c_long
            free_task_memory = ole32.CoTaskMemFree
            free_task_memory.argtypes = [ctypes.c_void_p]
            free_task_memory.restype = None
            result = int(
                get_known_folder_path(
                    ctypes.byref(folder_id), 0, None, ctypes.byref(profile_buffer)
                )
            )
            profile = profile_buffer.value
            if result != 0 or type(profile) is not str or not profile:
                raise ValueError
            return profile
        except Exception:
            raise _ParentLaunchError("user_profile_directory_unavailable") from None
        finally:
            if profile_buffer.value and ole32 is not None:
                free_task_memory = ole32.CoTaskMemFree
                free_task_memory.argtypes = [ctypes.c_void_p]
                free_task_memory.restype = None
                free_task_memory(ctypes.cast(profile_buffer, ctypes.c_void_p))


def _create_parent_api(backend_module: ModuleType) -> _Win32ParentApi:
    """Load the fixed native API only after the public source gate passes."""

    if os.name != "nt":
        raise _ParentLaunchError("windows_required")
    if type(backend_module) is not ModuleType:
        raise _ParentLaunchError("job_backend_source_invalid")
    return _Win32ParentApi(backend_module)


def _owned_handle_set(state: dict[str, Any]) -> set[int]:
    handles = state.get("owned_handles")
    if type(handles) is not set:
        handles = set()
        state["owned_handles"] = handles
    return handles


def _closed_handle_set(state: dict[str, Any]) -> set[int]:
    handles = state.get("closed_handles")
    if type(handles) is not set:
        handles = set()
        state["closed_handles"] = handles
    return handles


def _track_owned_handle(state: dict[str, Any], handle: Any) -> None:
    if type(state) is dict and type(handle) is int and handle > 0:
        if handle not in _closed_handle_set(state):
            _owned_handle_set(state).add(handle)


def _record_handle_closed(state: dict[str, Any], handle: int) -> None:
    _owned_handle_set(state).discard(handle)
    _closed_handle_set(state).add(handle)


def _forget_attribute_state(state: dict[str, Any]) -> None:
    """Drop attribute-list buffers only after a confirmed Delete call."""

    if type(state) is not dict:
        return
    state["attribute_list_open"] = False
    state["attribute_setup_uncertain"] = False
    for name in (
        "attribute_list",
        "attribute_storage",
        "job_array",
        "handle_array",
    ):
        state.pop(name, None)


def _record_stream_closed(state: dict[str, Any], stream: Any) -> bool:
    """Record raw-handle ownership released by one known stream close."""

    handles = state.get("stream_handle_by_id")
    if type(handles) is not dict:
        return False
    handle = handles.get(id(stream))
    if type(handle) is not int or handle <= 0:
        return False
    if getattr(stream, "closed", False) is not True:
        return False
    state.setdefault("fd_owned_handles", set()).discard(handle)
    state.setdefault("fd_close_uncertain_handles", set()).discard(handle)
    state.setdefault("fd_closed_handles", set()).add(handle)
    state.setdefault("fd_by_handle", {}).pop(handle, None)
    _record_handle_closed(state, handle)
    return True


def _capture_pipe(capture: _PipeCapture) -> None:
    try:
        while True:
            chunk = capture.stream.read(64 * 1024)
            if not chunk:
                capture.eof = True
                return
            if len(capture.data) + len(chunk) > capture.maximum:
                capture.overflow = True
            elif not capture.overflow:
                capture.data.extend(chunk)
    except BaseException:
        capture.failed = True
    finally:
        try:
            capture.stream.close()
            capture.closed = True
        except BaseException:
            capture.failed = True


def _fixed_bootstrap_code(frame_write_handle: int, *, child_mode: str = "activation") -> str:
    if type(frame_write_handle) is not int or frame_write_handle <= 0:
        raise RootDriverError("frame_channel_handle_invalid")
    if type(child_mode) is not str or child_mode not in _GATE_MODES:
        raise RootDriverError("fixed_child_mode_invalid")
    return (
        "import runpy,sys\n"
        "if sys.flags.optimize != 0: raise SystemExit(2)\n"
        f"sys.{_BOOTSTRAP_SENTINEL}=object()\n"
        f"sys.{_BOOTSTRAP_HANDLE}={frame_write_handle}\n"
        f"sys.{_BOOTSTRAP_MODE}={child_mode!r}\n"
        f"sys.argv=[{_CHILD_WRAPPER_PATH!r}]\n"
        f"runpy.run_path({_CHILD_WRAPPER_PATH!r},run_name='__main__')\n"
    )


def _validated_user_profile(value: Any) -> str:
    """Accept only a fully qualified, normalized OS profile directory."""

    if type(value) is not str or not value or "\0" in value:
        raise RootDriverError("user_profile_directory_invalid")
    drive, tail = ntpath.splitdrive(value)
    if (
        not drive
        or not tail.startswith(("\\", "/"))
        or not ntpath.isabs(value)
        or ntpath.normpath(value) != value
        or len(tail) < 2
        or any(ord(char) < 32 or char in '<>:"|?*' for char in tail)
        or value.startswith(("\\\\.\\", "\\\\?\\"))
    ):
        raise RootDriverError("user_profile_directory_invalid")
    return value


def _fixed_environment(api: Any) -> dict[str, str]:
    root = api.windows_directory()
    if type(root) is not str or not root or "\0" in root:
        raise RootDriverError("windows_directory_invalid")
    root = root.rstrip("\\/")
    profile = _validated_user_profile(api.user_profile_directory())
    values = {
        "SystemRoot": root,
        "WINDIR": root,
        "PATH": root + "\\System32;" + root,
        "TEMP": root + "\\Temp",
        "TMP": root + "\\Temp",
        "USERPROFILE": profile,
    }
    if any(type(value) is not str or "\0" in value for value in values.values()):
        raise RootDriverError("parent_environment_invalid")
    return values


def _validate_fixed_environment(api: Any, env: Any) -> dict[str, str]:
    """Rebuild the OS-derived allowlist and reject any caller-added entries."""

    expected = _fixed_environment(api)
    if type(env) not in (dict, MappingProxyType) or dict(env) != expected:
        raise _ParentLaunchError("parent_environment_binding_invalid")
    return expected


def _child_argv(frame_write_handle: int, *, child_mode: str = "activation") -> tuple[str, ...]:
    return (
        _PYTHON_EXE_PATH,
        "-I",
        "-S",
        "-B",
        "-c",
        _fixed_bootstrap_code(frame_write_handle, child_mode=child_mode),
    )


def _join_reader(capture: _PipeCapture, timeout: float) -> bool:
    thread = capture.thread
    if not isinstance(thread, threading.Thread):
        return False
    try:
        thread.join(timeout=max(0.0, timeout))
        return not thread.is_alive()
    except Exception:
        return False


def _job_active_until(api: Any, job: int, *, expected: int, timeout: float) -> str:
    """Return a bounded, three-state Job observation.

    ``None`` and malformed counts mean unobserved; only repeated exact
    positive counts through the deadline prove that termination is allowed.
    """

    if type(expected) is not int or expected < 0 or type(timeout) not in (int, float):
        return "unobserved"
    deadline = time.monotonic() + timeout
    last_active: int | None = None
    while True:
        try:
            active = api.query_job_active(job)
        except Exception:
            return "unobserved"
        if type(active) is not int or active < 0:
            return "unobserved"
        if active == expected:
            return "matched"
        last_active = active
        if time.monotonic() >= deadline:
            return "nonzero" if last_active > 0 else "zero_mismatch"
        try:
            api.sleep(_JOB_ZERO_POLL_SECONDS)
        except Exception:
            return "unobserved"


def _retain_uncertain_native_call(lease: Any, state: Mapping[str, Any]) -> None:
    """Retain every live native control and source on an uncertain path."""

    if type(_PARENT_NATIVE_KEEPALIVE) is not list:
        return
    reference = (lease, state)
    if not any(
        type(item) is tuple and len(item) == 2 and item[0] is lease
        for item in _PARENT_NATIVE_KEEPALIVE
    ):
        _PARENT_NATIVE_KEEPALIVE.append(reference)


def _cleanup_unstarted_native_call(api: Any, state: dict[str, Any]) -> bool:
    """Release pipes and an empty Job when no child was created."""

    if state.get("controls") is not None:
        return False
    clean = True
    if state.get("pipe_setup_uncertain") is True or state.get("stdin_setup_uncertain") is True:
        clean = False
    if state.get("create_attempted") is True and state.get("process_creation_uncertain") is True:
        clean = False
    if state.get("attribute_setup_uncertain") is True:
        clean = False
    elif state.get("attribute_list_open") is True:
        delete_attribute_state = getattr(api, "delete_attribute_state", None)
        if not callable(delete_attribute_state) or delete_attribute_state(state) is not True:
            clean = False
    elif state.get("attribute_list_open") not in (None, False):
        clean = False

    transferred = state.get("fd_owned_handles", set())
    if type(transferred) is not set:
        clean = False
        transferred = set()
    closed_handles = _closed_handle_set(state)
    for stream in state.get("streams", ()):
        try:
            if not getattr(stream, "closed", False):
                stream.close()
            if getattr(stream, "closed", False) and not _record_stream_closed(state, stream):
                clean = False
        except Exception:
            clean = False
    if (
        state.get("fd_close_uncertain_handles")
        or state.get("fd_conversion_uncertain_handles")
        or state.get("fd_by_handle")
    ):
        clean = False
    # Raw handles transferred to a CRT fd/stream are never passed to
    # CloseHandle again. Only handles that remain in the raw ownership set
    # reach this loop.
    owned_handles = _owned_handle_set(state)
    if transferred & owned_handles:
        clean = False
    uncertain_fd_handles = set(state.get("fd_close_uncertain_handles", ()))
    uncertain_fd_handles.update(state.get("fd_conversion_uncertain_handles", ()))
    for handle in tuple(owned_handles):
        if handle in uncertain_fd_handles:
            # The numeric HANDLE may already belong to a CRT fd. Keep both
            # records alive and never issue a second CloseHandle.
            clean = False
            continue
        if handle in closed_handles:
            owned_handles.discard(handle)
            continue
        try:
            if api.close_handle(handle) is True:
                _record_handle_closed(state, handle)
            else:
                clean = False
        except Exception:
            clean = False
    job = state.get("job")
    if type(job) is int and job > 0:
        try:
            active = api.query_job_active(job)
        except Exception:
            active = None
        if type(active) is not int or active != 0 or api.close_handle(job) is not True:
            clean = False
        else:
            state["job_closed"] = True
            _record_handle_closed(state, job)
    state["closed_handles"] = closed_handles
    return clean


def _cleanup_unstarted_or_retain(
    lease: C01V20OuterSourceLease, api: Any, state: dict[str, Any]
) -> BaseException | None:
    """Retain uncertain native state and return any cleanup interruption.

    Callers use the returned exception as secondary context so a cleanup
    interruption cannot replace the failure that entered this cleanup path.
    """

    try:
        clean = _cleanup_unstarted_native_call(api, state)
    except BaseException as cleanup_error:
        _retain_uncertain_native_call(lease, state)
        return cleanup_error
    if clean is not True:
        _retain_uncertain_native_call(lease, state)
    return None


def _cleanup_failed_process_creation(
    api: Any, state: dict[str, Any], controls: _ParentProcessControls
) -> bool:
    """Close fixed setup resources after CreateProcessW definitively failed.

    A false CreateProcessW result means there is no child to retain. Release
    any partially populated PROCESS_INFORMATION handles and the attribute list
    before allowing the ordinary unstarted-pipe/empty-Job cleanup path.
    """

    if type(controls) is not _ParentProcessControls or controls.created is not False:
        return False
    if api.delete_attributes(controls, state) is not True:
        state["controls"] = controls
        return False
    for name, closed_name in (("process", "process_closed"), ("thread", "thread_closed")):
        handle = getattr(controls, name, None)
        if type(handle) is not int or handle < 0:
            state["controls"] = controls
            return False
        if handle > 0:
            if api.close_handle(handle) is not True:
                state["controls"] = controls
                return False
            _record_handle_closed(state, handle)
            setattr(controls, closed_name, True)
    state["controls"] = None
    state["process_closed"] = True
    state["thread_closed"] = True
    return True


def _module_for_lease(lease: C01V20OuterSourceLease, path: str) -> ModuleType:
    if (
        type(lease) is not C01V20OuterSourceLease
        or type(lease.source_modules) is not MappingProxyType
        or type(lease.source_objects) is not MappingProxyType
        or type(lease.held_source_bytes) is not MappingProxyType
        or type(lease.source_pins) is not MappingProxyType
        or path not in lease.source_modules
        or path not in lease.source_objects
        or path not in lease.source_pins
        or path not in lease.held_source_bytes
    ):
        raise RootDriverError("held_module_missing")
    module = lease.source_modules[path]
    if (
        type(module) is not ModuleType
        or module.__dict__ is not vars(module)
        or module.__dict__.get("__c01_source_sha256__") != lease.source_pins[path]
        or hashlib.sha256(lease.held_source_bytes[path]).hexdigest() != lease.source_pins[path]
        or not _source_path_matches(module.__dict__.get("__file__"), path)
        or not _validate_source_module_snapshots(
            {path: module},
            {path: lease.source_objects[path]},
            {path: lease.source_pins[path]},
            {path: lease.held_source_bytes[path]},
        )
    ):
        raise RootDriverError("held_module_binding_invalid")
    return module


def _claim_activation_attempt(lease: C01V20OuterSourceLease, call_nonce: object) -> None:
    """Atomically consume the gate proof and host-wide activation attempt."""

    with _ACTIVATION_LOCK:
        if (
            type(_HOST_ACTIVATION_STATE) is not dict
            or set(_HOST_ACTIVATION_STATE)
            != {"used", "lease", "call_nonce", "gate_receipt"}
            or _HOST_ACTIVATION_STATE.get("used") is not False
            or _HOST_ACTIVATION_STATE.get("lease") is not None
            or _HOST_ACTIVATION_STATE.get("call_nonce") is not None
            or _HOST_ACTIVATION_STATE.get("gate_receipt") is not None
            or type(_PARENT_NATIVE_KEEPALIVE) is not list
            or _PARENT_NATIVE_KEEPALIVE
            or _outer_lease_current(lease, require_entered=True) is not True
            or type(call_nonce) is not object
            or lease.activation_started is not False
            or lease.activation_nonce is not None
            or lease.supervisor_started is not False
        ):
            raise RootDriverError("parent_activation_already_consumed")
        with _CREDENTIAL_FREE_GATE_LOCK:
            gate_receipt = (
                _CREDENTIAL_FREE_GATE_STATE.get("receipt")
                if type(_CREDENTIAL_FREE_GATE_STATE) is dict
                else None
            )
            if (
                type(_CREDENTIAL_FREE_GATE_STATE) is not dict
                or set(_CREDENTIAL_FREE_GATE_STATE) != {"used", "receipt"}
                or _CREDENTIAL_FREE_GATE_STATE.get("used") is not True
                or type(gate_receipt) is not C01V20CredentialFreeGateReceipt
                or validate_c01_v20_credential_free_gate_receipt(gate_receipt) is not True
                or gate_receipt.status != "PASS"
                or _credential_free_gate_current_for(lease) is not True
                or gate_receipt._outer_close_receipt.public_source_pins
                != lease.public_source_pins
                or gate_receipt._outer_close_receipt.software_source_pins
                != lease.software_source_pins
                or gate_receipt._outer_close_receipt.source_modules.get(_DRIVER_PATH)
                is not lease.source_modules.get(_DRIVER_PATH)
            ):
                raise RootDriverError("parent_activation_gate_receipt_invalid")
            _HOST_ACTIVATION_STATE["used"] = True
            _HOST_ACTIVATION_STATE["lease"] = lease
            _HOST_ACTIVATION_STATE["call_nonce"] = call_nonce
            _HOST_ACTIVATION_STATE["gate_receipt"] = gate_receipt
        object.__setattr__(lease, "activation_started", True)
        object.__setattr__(lease, "activation_nonce", call_nonce)


def _claim_credential_free_gate(lease: C01V20OuterSourceLease, call_nonce: object) -> None:
    """Consume the separate host gate exactly once before native setup."""

    with _CREDENTIAL_FREE_GATE_LOCK:
        if (
            type(_CREDENTIAL_FREE_GATE_STATE) is not dict
            or set(_CREDENTIAL_FREE_GATE_STATE) != {"used", "receipt"}
            or _CREDENTIAL_FREE_GATE_STATE["used"] is not False
            or _CREDENTIAL_FREE_GATE_STATE["receipt"] is not None
            or type(_PARENT_NATIVE_KEEPALIVE) is not list
            or _PARENT_NATIVE_KEEPALIVE
            or type(lease) is not C01V20OuterSourceLease
            or _outer_lease_current(lease, require_entered=True) is not True
            or type(call_nonce) is not object
            or lease.activation_started is not False
            or lease.credential_free_gate_started is not False
            or lease.credential_free_gate_nonce is not None
            or lease.credential_free_gate_supervisor_started is not False
        ):
            raise RootDriverError("credential_free_gate_already_consumed")
        _CREDENTIAL_FREE_GATE_STATE["used"] = True
        object.__setattr__(lease, "credential_free_gate_started", True)
        object.__setattr__(lease, "credential_free_gate_nonce", call_nonce)


def _claim_supervisor_entry(
    lease: C01V20OuterSourceLease, call_nonce: object, *, child_mode: str
) -> None:
    """Mark the one fixed supervisor route before any parent native setup."""

    with _ACTIVATION_LOCK:
        if type(lease) is not C01V20OuterSourceLease:
            raise RootDriverError("parent_activation_lease_invalid")
        if child_mode == "activation" and lease.activation_started is False:
            if type(_PARENT_NATIVE_KEEPALIVE) is not list or _PARENT_NATIVE_KEEPALIVE:
                raise RootDriverError("parent_native_call_already_retained")
            if _outer_lease_current(lease, require_entered=True) is not True:
                raise RootDriverError("parent_activation_lease_invalid")
            if type(call_nonce) is not object:
                raise RootDriverError("parent_activation_nonce_invalid")
            object.__setattr__(lease, "activation_started", True)
            object.__setattr__(lease, "activation_nonce", call_nonce)
        if child_mode == "activation" and (
            type(_PARENT_NATIVE_KEEPALIVE) is not list
            or _PARENT_NATIVE_KEEPALIVE
            or type(_HOST_ACTIVATION_STATE) is not dict
            or set(_HOST_ACTIVATION_STATE)
            != {"used", "lease", "call_nonce", "gate_receipt"}
            or _HOST_ACTIVATION_STATE.get("used") is not True
            or _HOST_ACTIVATION_STATE.get("lease") is not lease
            or _HOST_ACTIVATION_STATE.get("call_nonce") is not call_nonce
            or type(_HOST_ACTIVATION_STATE.get("gate_receipt"))
            is not C01V20CredentialFreeGateReceipt
            or type(_CREDENTIAL_FREE_GATE_STATE) is not dict
            or _CREDENTIAL_FREE_GATE_STATE.get("used") is not True
            or _CREDENTIAL_FREE_GATE_STATE.get("receipt")
            is not _HOST_ACTIVATION_STATE.get("gate_receipt")
            or validate_c01_v20_credential_free_gate_receipt(
                _HOST_ACTIVATION_STATE.get("gate_receipt")
            )
            is not True
            or lease.activation_started is not True
            or lease.activation_nonce is not call_nonce
            or lease.supervisor_started is not False
        ):
            raise RootDriverError("parent_activation_already_consumed")
        if child_mode == "activation":
            object.__setattr__(lease, "supervisor_started", True)
            return
        if (
            child_mode != "credential_free_gate"
            or type(_CREDENTIAL_FREE_GATE_STATE) is not dict
            or _CREDENTIAL_FREE_GATE_STATE.get("used") is not True
            or lease.credential_free_gate_started is not True
            or lease.credential_free_gate_nonce is not call_nonce
            or lease.credential_free_gate_supervisor_started is not False
            or type(_PARENT_NATIVE_KEEPALIVE) is not list
            or _PARENT_NATIVE_KEEPALIVE
        ):
            raise RootDriverError("credential_free_gate_supervisor_replayed")
        object.__setattr__(lease, "credential_free_gate_supervisor_started", True)


def _supervise_fixed_child(
    lease: C01V20OuterSourceLease,
    api: Any,
    call_nonce: object,
    *,
    child_mode: str = "activation",
) -> C01V20ParentProcessReceipt:
    """Run the one fixed child and collect all three independent channels.

    This function is internal so the public Root caller cannot supply an argv,
    environment, handle, or native launch implementation.
    """

    if type(child_mode) is not str or child_mode not in _GATE_MODES:
        raise RootDriverError("fixed_child_mode_invalid")
    _claim_supervisor_entry(lease, call_nonce, child_mode=child_mode)
    if (
        _outer_lease_current(lease, require_entered=True) is not True
        or type(call_nonce) is not object
        or type(lease.public_source_pins) is not MappingProxyType
        or type(lease.software_source_pins) is not MappingProxyType
        or lease.software_source_pins.get(_PYTHON_EXE_PATH) != _PYTHON_EXE_SHA256
        or lease.software_source_pins.get(_PYTHON_DLL_PATH) != _PYTHON_DLL_SHA256
        or lease.source_modules is None
        or lease.source_objects is None
        or lease.held_source_bytes is None
        or lease.held_software_bytes is None
        or not _validate_source_module_snapshots(
            lease.source_modules,
            lease.source_objects,
            lease.source_pins,
            lease.held_source_bytes,
        )
    ):
        raise RootDriverError("parent_source_preflight_failed")

    driver_module = _module_for_lease(lease, _DRIVER_PATH)
    if (
        driver_module.__dict__ is not globals()
        or driver_module.__name__ != MODULE_NAME
        or validate_c01_v20_driver_source_objects(driver_module, lease.source_objects[_DRIVER_PATH])
        is not True
        or _source_root_for_driver().replace("\\", "/").casefold() != _ROOT_DIRECTORY.casefold()
    ):
        raise RootDriverError("parent_driver_source_preflight_failed")
    wrapper_module = _module_for_lease(lease, _WRAPPER_PATH)
    handoff_module = _module_for_lease(lease, _HANDOFF_PATH)
    backend_module = _module_for_lease(lease, _JOB_BACKEND_PATH)
    _require_captured_function(
        wrapper_module, lease.source_objects[_WRAPPER_PATH], "create_c01_v20_wrapper_call_receipt"
    )
    _require_captured_function(
        wrapper_module, lease.source_objects[_WRAPPER_PATH], "validate_c01_v20_wrapper_call_receipt"
    )
    if child_mode == "credential_free_gate":
        _require_captured_function(
            wrapper_module,
            lease.source_objects[_WRAPPER_PATH],
            "invoke_c01_v20_credential_free_gate",
        )
    for name in ("_load_kernel32", "_create_job", "_query_job_active_processes", "_as_handle"):
        _require_captured_function(backend_module, lease.source_objects[_JOB_BACKEND_PATH], name)
    parse_frame = _require_captured_function(
        handoff_module, lease.source_objects[_HANDOFF_PATH], "read_c01_root_content_frame"
    )

    python_bytes = lease.held_software_bytes.get(_PYTHON_EXE_PATH)
    dll_bytes = lease.held_software_bytes.get(_PYTHON_DLL_PATH)
    if (
        type(python_bytes) is not bytes
        or hashlib.sha256(python_bytes).hexdigest() != _PYTHON_EXE_SHA256
        or type(dll_bytes) is not bytes
        or hashlib.sha256(dll_bytes).hexdigest() != _PYTHON_DLL_SHA256
    ):
        raise RootDriverError("parent_interpreter_pin_invalid")

    state: dict[str, Any] = {
        "lease": lease,
        "api": api,
        "job": None,
        "controls": None,
        "pipes": [],
        "streams": [],
        "captures": [],
        "stream_handles": set(),
        "process_closed": False,
        "thread_closed": False,
        "job_closed": False,
        "forced": False,
        "process_create_call_count": 0,
        "owned_handles": set(),
        "closed_handles": set(),
        "fd_owned_handles": set(),
        "fd_closed_handles": set(),
        "fd_close_uncertain_handles": set(),
        "fd_conversion_uncertain_handles": set(),
        "fd_by_handle": {},
        "stream_handle_by_id": {},
    }
    try:
        stdout_read, stdout_write = api.create_pipe(state)
        stderr_read, stderr_write = api.create_pipe(state)
        frame_read, frame_write = api.create_pipe(state)
        for pair in (
            (stdout_read, stdout_write),
            (stderr_read, stderr_write),
            (frame_read, frame_write),
        ):
            if pair not in state["pipes"]:
                state["pipes"].append(pair)
            _track_owned_handle(state, pair[0])
            _track_owned_handle(state, pair[1])
        stdin_handle = api.open_null_input(state)
        state["stdin_handle"] = stdin_handle
        _track_owned_handle(state, stdin_handle)
        stdout_stream = api.open_read_stream(stdout_read, state)
        state["streams"].append(stdout_stream)
        state["stream_handles"].add(stdout_read)
        state["stream_handle_by_id"].setdefault(id(stdout_stream), stdout_read)
        state["fd_owned_handles"].add(stdout_read)
        state["owned_handles"].discard(stdout_read)
        stderr_stream = api.open_read_stream(stderr_read, state)
        state["streams"].append(stderr_stream)
        state["stream_handles"].add(stderr_read)
        state["stream_handle_by_id"].setdefault(id(stderr_stream), stderr_read)
        state["fd_owned_handles"].add(stderr_read)
        state["owned_handles"].discard(stderr_read)
        frame_stream = api.open_read_stream(frame_read, state)
        state["streams"].append(frame_stream)
        state["stream_handles"].add(frame_read)
        state["stream_handle_by_id"].setdefault(id(frame_stream), frame_read)
        state["fd_owned_handles"].add(frame_read)
        state["owned_handles"].discard(frame_read)
        captures = [
            _PipeCapture(stdout_stream, MAX_PUBLIC_PROJECTION_BYTES),
            _PipeCapture(stderr_stream, MAX_STDERR_BYTES),
            _PipeCapture(frame_stream, MAX_FRAME_BYTES),
        ]
        state["captures"] = captures
        job = api.create_job()
        if type(job) is not int or job <= 0:
            raise _ParentLaunchError("parent_job_invalid")
        state["job"] = job
        child_argv = _child_argv(frame_write, child_mode=child_mode)
        environment = _fixed_environment(api)
        controls = api.create_suspended_process(
            job=job,
            inherited_handles=(stdin_handle, stdout_write, stderr_write, frame_write),
            stdio_handles=(stdin_handle, stdout_write, stderr_write),
            argv=child_argv,
            cwd=_ROOT_DIRECTORY,
            env=MappingProxyType(environment),
            state=state,
        )
        state["controls"] = controls
        if type(controls) is _ParentProcessControls and controls.created is False:
            if _cleanup_failed_process_creation(api, state, controls):
                raise _ParentLaunchError("parent_process_create_failed")
            raise _ParentLaunchError(
                "parent_process_create_cleanup_uncertain",
                controls=controls,
                uncertain=True,
            )
        if (
            type(controls) is not _ParentProcessControls
            or controls.job != job
            or controls.created is not True
            or controls.process <= 0
            or controls.thread <= 0
            or controls.pid <= 0
        ):
            raise _ParentLaunchError("parent_process_create_failed", controls=controls)
        if api.delete_attributes(controls, state) is not True:
            raise _ParentLaunchError(
                "parent_attribute_list_delete_failed", controls=controls, uncertain=True
            )
        if _job_active_until(api, job, expected=1, timeout=1.0) != "matched":
            raise _ParentLaunchError(
                "parent_job_assignment_unverified", controls=controls, uncertain=True
            )

        for capture in captures:
            thread = threading.Thread(
                target=_capture_pipe,
                args=(capture,),
                name="c01-v20-parent-reader",
                daemon=False,
            )
            capture.thread = thread
            thread.start()

        close_failures = []
        for handle in (stdout_write, stderr_write, frame_write, stdin_handle):
            if api.close_handle(handle) is not True:
                close_failures.append(handle)
            else:
                _record_handle_closed(state, handle)
        if close_failures:
            raise _ParentLaunchError(
                "parent_inherited_handle_close_failed", controls=controls, uncertain=True
            )
        state["inherited_handles_closed"] = True

        if api.resume_thread(controls.thread) is not True:
            raise _ParentLaunchError("parent_resume_failed", controls=controls, uncertain=True)
        controls.resumed = True
        if api.close_handle(controls.thread) is not True:
            raise _ParentLaunchError(
                "parent_thread_handle_close_failed", controls=controls, uncertain=True
            )
        controls.thread_closed = True
        state["thread_closed"] = True
        _record_handle_closed(state, controls.thread)

        wait_result = api.wait_process(controls.process, int(_CHILD_TIMEOUT_SECONDS * 1000))
        if wait_result == "timeout":
            controls.forced = True
            state["forced"] = True
            if api.terminate_job(job) is not True:
                raise _ParentLaunchError(
                    "parent_job_termination_uncertain", controls=controls, uncertain=True
                )
            wait_result = api.wait_process(
                controls.process, int(_FORCED_REAP_TIMEOUT_SECONDS * 1000)
            )
        if wait_result != "signaled":
            raise _ParentLaunchError(
                "parent_process_exit_unobserved", controls=controls, uncertain=True
            )
        exit_code = api.get_exit_code(controls.process)
        if type(exit_code) is not int or exit_code < 0:
            raise _ParentLaunchError(
                "parent_process_exit_code_unobserved", controls=controls, uncertain=True
            )

        # Root requires this reference to be released before Job accounting is
        # queried; a signaled wait and exit code alone may still show one.
        if api.close_handle(controls.process) is not True:
            raise _ParentLaunchError(
                "parent_process_handle_close_failed", controls=controls, uncertain=True
            )
        controls.process_closed = True
        state["process_closed"] = True
        _record_handle_closed(state, controls.process)

        job_zero_state = _job_active_until(api, job, expected=0, timeout=_JOB_ZERO_TIMEOUT_SECONDS)
        if job_zero_state == "unobserved":
            raise _ParentLaunchError(
                "parent_job_zero_unobserved", controls=controls, uncertain=True
            )
        if job_zero_state == "nonzero":
            controls.forced = True
            state["forced"] = True
            if api.terminate_job(job) is not True:
                raise _ParentLaunchError(
                    "parent_job_descendant_termination_uncertain", controls=controls, uncertain=True
                )
            reaped = _job_active_until(api, job, expected=0, timeout=_FORCED_REAP_TIMEOUT_SECONDS)
            if reaped == "unobserved":
                raise _ParentLaunchError(
                    "parent_job_descendant_zero_unobserved",
                    controls=controls,
                    uncertain=True,
                )
            if reaped != "matched":
                raise _ParentLaunchError(
                    "parent_job_descendant_retained", controls=controls, uncertain=True
                )
        elif job_zero_state != "matched":
            raise _ParentLaunchError(
                "parent_job_zero_unobserved", controls=controls, uncertain=True
            )

        all_joined = True
        for capture in captures:
            if not _join_reader(capture, _READER_JOIN_TIMEOUT_SECONDS):
                all_joined = False
        if not all_joined:
            raise _ParentLaunchError(
                "parent_reader_join_uncertain", controls=controls, uncertain=True
            )
        for capture in captures:
            if not _record_stream_closed(state, capture.stream):
                raise _ParentLaunchError(
                    "parent_reader_handle_close_unverified",
                    controls=controls,
                    uncertain=True,
                )
        if api.close_handle(job) is not True:
            raise _ParentLaunchError(
                "parent_job_handle_close_failed", controls=controls, uncertain=True
            )
        controls.job_closed = True
        state["job_closed"] = True
        _record_handle_closed(state, job)

        if any(
            capture.eof is not True
            or capture.closed is not True
            or capture.overflow is True
            or capture.failed is True
            for capture in captures
        ):
            raise _ParentLaunchError(
                "parent_pipe_capture_invalid", controls=controls, uncertain=True
            )
        stdout_raw = bytes(captures[0].data)
        stderr_raw = bytes(captures[1].data)
        frame_raw = bytes(captures[2].data)
        if not stdout_raw or stderr_raw:
            raise _ParentLaunchError("parent_child_output_invalid", controls=controls)

        projection = _parse_canonical_projection(stdout_raw)
        if child_mode == "credential_free_gate":
            if not _validate_credential_free_gate_projection(projection):
                raise _ParentLaunchError("parent_gate_projection_invalid", controls=controls)
        elif not _validate_driver_projection(projection):
            raise _ParentLaunchError("parent_child_projection_invalid", controls=controls)
        frame = None
        if frame_raw:
            if child_mode == "credential_free_gate":
                raise _ParentLaunchError("credential_free_gate_frame_not_empty", controls=controls)
            frame = parse_frame(io.BytesIO(frame_raw))
            if (
                type(frame) is not handoff_module.__dict__.get("RootContentFrame")
                or getattr(frame, "_raw", None) != frame_raw
            ):
                raise _ParentLaunchError("parent_content_frame_binding_invalid", controls=controls)
        if child_mode == "credential_free_gate":
            if frame is not None or frame_raw:
                raise _ParentLaunchError("credential_free_gate_frame_not_empty", controls=controls)
            if controls.forced is False and (
                (projection["status"] == "PASS" and exit_code != 0)
                or (projection["status"] == "BLOCKED" and exit_code != 2)
            ):
                raise _ParentLaunchError("credential_free_gate_exit_mismatch", controls=controls)
        elif controls.forced is False:
            if projection["receipt_verified"] is True:
                if frame is None or exit_code != 0:
                    raise _ParentLaunchError("parent_child_candidate_unbound", controls=controls)
            elif frame is not None:
                raise _ParentLaunchError("parent_child_blocked_frame_present", controls=controls)

        all_native_handles_closed = (
            controls.process_closed
            and controls.thread_closed
            and controls.job_closed
            and state.get("inherited_handles_closed") is True
            and all(capture.closed is True for capture in captures)
        )
        receipt = create_c01_v20_parent_process_receipt(
            frame=frame,
            handoff_module=handoff_module,
            call_nonce=call_nonce,
            stdout_raw=stdout_raw,
            stderr_raw=stderr_raw,
            child_pid=controls.pid,
            exit_code=exit_code,
            launch_count=state.get("process_create_call_count"),
            job_assigned_before_resume=True,
            job_empty=True,
            stdout_eof=captures[0].eof,
            stderr_eof=captures[1].eof,
            frame_eof=captures[2].eof,
            frame_payload_bytes=len(frame_raw),
            job_handles_closed=all_native_handles_closed,
            reader_threads_joined=all_joined,
            overflow_observed=False,
            reader_failed=False,
            forced_termination=controls.forced,
        )
        return receipt
    except _ParentLaunchError as exc:
        if exc.controls is not None and state.get("controls") is None:
            state["controls"] = exc.controls
        cleanup_error = None
        if (
            exc.uncertain
            or state.get("process_creation_uncertain") is True
            or state.get("controls") is not None
        ):
            _retain_uncertain_native_call(lease, state)
        else:
            cleanup_error = _cleanup_unstarted_or_retain(lease, api, state)
        primary_error = RootDriverError(exc.code)
        if cleanup_error is not None:
            raise primary_error from cleanup_error
        raise primary_error from None
    except RootDriverError as exc:
        if state.get("controls") is not None:
            _retain_uncertain_native_call(lease, state)
        else:
            cleanup_error = _cleanup_unstarted_or_retain(lease, api, state)
            if cleanup_error is not None:
                raise exc from cleanup_error
        raise
    except Exception:
        _retain_uncertain_native_call(lease, state)
        raise
    except BaseException:
        _retain_uncertain_native_call(lease, state)
        raise


def run_root_activation(lease: C01V20OuterSourceLease) -> Any:
    """Run one fixed, read-only V20 child through the parent Job boundary.

    Root must enter the exact CUv2 source lease and bind its compiled module
    snapshots before calling this function. The function owns the only child
    launch path; it accepts no command, handle, namespace, profile, or output
    callback from the caller.
    """

    if (
        _outer_lease_current(lease, require_entered=True) is not True
        or _credential_free_gate_current_for(lease) is not True
        or type(lease.source_modules) is not MappingProxyType
        or type(lease.source_objects) is not MappingProxyType
        or not _validate_source_module_snapshots(
            lease.source_modules,
            lease.source_objects,
            lease.source_pins,
            lease.held_source_bytes,
        )
    ):
        raise RootDriverError("root_activation_source_lease_invalid")
    backend_module = _module_for_lease(lease, _JOB_BACKEND_PATH)
    _require_captured_function(
        backend_module, lease.source_objects[_JOB_BACKEND_PATH], "_load_kernel32"
    )
    _require_captured_function(
        backend_module, lease.source_objects[_JOB_BACKEND_PATH], "_create_job"
    )
    _require_captured_function(
        backend_module, lease.source_objects[_JOB_BACKEND_PATH], "_query_job_active_processes"
    )
    call_nonce = object()
    _claim_activation_attempt(lease, call_nonce)
    api = _create_parent_api(backend_module)
    process_receipt = _supervise_fixed_child(lease, api, call_nonce)
    projection = _parse_canonical_projection(process_receipt.stdout_raw)
    wrapper_module = _module_for_lease(lease, _WRAPPER_PATH)
    wrapper_call_receipt = None
    if process_receipt.frame is not None and process_receipt.forced_termination is False:
        create_wrapper_receipt = _require_captured_function(
            wrapper_module,
            lease.source_objects[_WRAPPER_PATH],
            "create_c01_v20_wrapper_call_receipt",
        )
        try:
            wrapper_call_receipt = create_wrapper_receipt(
                process_receipt.stdout_raw,
                process_receipt.frame,
                process_receipt,
                parent_driver_module=lease.source_modules[_DRIVER_PATH],
                parent_driver_objects=lease.source_objects[_DRIVER_PATH],
            )
        except Exception:
            wrapper_call_receipt = None
    outer_close = create_c01_v20_outer_close_receipt(
        lease=lease, parent_process_receipt=process_receipt
    )
    if process_receipt.forced_termination is True:
        return _forced_cleanup_blocked_result(outer_close)
    if wrapper_call_receipt is None:
        return {
            "case_id": CASE_ID,
            "certification": "BLOCKED",
            "mode": PROFILE_ID,
            "profile": PROFILE_ID,
            "reason": projection.get("reason", "parent_wrapper_receipt_blocked"),
            "write_policy": "NO_WRITE",
            "writes": 0,
            "formal_c01_pass": False,
            "official_c01_pass_count": 0,
            "forced_cleanup": False,
            "request_count": 0,
            "query_callback_count": 0,
            "snapshot_count": 0,
            "write_invocation_count": 0,
            "source_authenticity_verified": False,
            "account_binding_verified": False,
            "source_closure_verified": False,
            "root_postverify_verified": False,
            "outer_postverify_verified": outer_close.outer_postverify_verified,
            "outer_close_verified": outer_close.normal_close_verified,
            "cleanup_verified": outer_close.cleanup_verified,
        }
    try:
        return complete_c01_v20_formal_result(
            frame=process_receipt.frame,
            parent_process_receipt=process_receipt,
            wrapper_call_receipt=wrapper_call_receipt,
            outer_close_receipt=outer_close,
        )
    except RootDriverError:
        return {
            "case_id": CASE_ID,
            "certification": "BLOCKED",
            "mode": PROFILE_ID,
            "profile": PROFILE_ID,
            "reason": "root_formal_adjudication_blocked",
            "write_policy": "NO_WRITE",
            "writes": 0,
            "formal_c01_pass": False,
            "official_c01_pass_count": 0,
            "forced_cleanup": False,
            "request_count": 0,
            "query_callback_count": 0,
            "snapshot_count": 0,
            "write_invocation_count": 0,
            "source_authenticity_verified": False,
            "account_binding_verified": False,
            "source_closure_verified": False,
            "root_postverify_verified": False,
            "outer_postverify_verified": True,
            "outer_close_verified": True,
            "cleanup_verified": True,
        }


__all__ = [
    "C01V20CredentialFreeGateReceipt",
    "C01V20OuterCloseReceipt",
    "C01V20OuterSourceLease",
    "C01V20ParentProcessReceipt",
    "RootDriverError",
    "bind_c01_v20_outer_source_modules",
    "capture_c01_v20_driver_objects",
    "complete_c01_v20_formal_result",
    "create_c01_v20_outer_close_receipt",
    "create_c01_v20_parent_process_receipt",
    "enter_c01_v20_outer_source_lease",
    "run_root_activation",
    "run_root_credential_free_job_channel_gate",
    "validate_c01_v20_outer_close_receipt",
    "validate_c01_v20_parent_process_receipt",
    "validate_c01_v20_credential_free_gate_receipt",
    "validate_c01_v20_driver_source_objects",
]
