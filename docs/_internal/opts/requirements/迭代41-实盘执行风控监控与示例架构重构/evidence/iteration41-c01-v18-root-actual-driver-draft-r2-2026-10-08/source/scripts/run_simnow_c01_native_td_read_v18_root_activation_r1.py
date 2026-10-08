"""One-shot Root activation for the frozen SimNow C01 V18 TD-read profile.

This source-only candidate is deliberately unregistered. The public entry
requires an exact self SHA-256 and explicit activation. Its V18 admission is
created only after the protected config and complete-pair selection have been
revalidated and the selected pair has been bound to a bounded credential read.
The child is this fixed wrapper in a Windows Job; it loads the exact V18 Root
entry and calls the issuer in that same child process. Only the opaque Root
case receipt can be serialized, after its scopes close and the outer Job drains.

Importing this module is inert. Fake tests inject ports into the private core;
the CLI always constructs the fixed production ports below. No V3 or V18 source
globals are patched.
"""

from __future__ import annotations

import ast
from contextlib import contextmanager
from dataclasses import dataclass, field as dataclass_field
from datetime import datetime, timedelta, timezone
import hashlib
import importlib.machinery
import json
import os
from pathlib import Path
import re
import secrets
import struct
import sys
import threading
import time
from types import FunctionType, MappingProxyType, ModuleType, SimpleNamespace
from typing import Any, Mapping, Optional, Sequence


PROFILE_ID = "C01_NATIVE_TD_READ_V18"
CASE_ID = "C01"
REPO_ROOT = Path("D:/source_code/backtrader")
_ENTRY_RELATIVE = "scripts/run_simnow_c01_native_td_read_v18_root_activation_r1.py"
_ROOT_ENTRY_RELATIVE = "backtrader_runtime/certification_simnow_c01_root_entry_v18.py"
_ROOT_ENTRY_SHA256 = "ea7221fdc5d156670376f64ae5302306e42a34af82411650ccec94336949ab30"
_V18_RELATIVE = "backtrader_runtime/certification_simnow_c01_native_td_read_v18.py"
_V18_SHA256 = "0f0026f1b2c217bf124bc8ba5ebe44a00d7c86eb096975f2cd76c7eb850b44ab"
_V18_MANIFEST_RELATIVE = "backtrader_runtime/certification_simnow_c01_native_td_read_v18.sources.json"
_V18_MANIFEST_SHA256 = "372ee3aefc9d7066fcbeb82253dd4798d7f74c0b9eea9337c3d0af58c702f70d"
_V18_SCHEMA_RELATIVE = "backtrader_runtime/certification_simnow_c01_native_td_read_v18.admission.schema.json"
_V18_SCHEMA_SHA256 = "02f4891ea2dc18b2125db05706779abf830eef33fd3c264b81104e3154333c54"
_CASE_RUNNER_RELATIVE = "examples/000_live_certification/simnow_penetration/cases/C01/run_v18.py"
_CASE_RUNNER_SHA256 = "507ca6c373a83fbbf7580a740c06d7ee5417701aba6c79bf02aea30810cc936e"
_PRIVATE_HELPER_RELATIVE = "backtrader_runtime/certification_roundtrip_private.py"
_PRIVATE_HELPER_SHA256 = "b866194bdc56d91cc7a6678e83b0af8e4e018ee53a2c136325344c2ee8a5ecfd"
_R3_CLI_HELPER_RELATIVE = "backtrader_runtime/certification_binance_roundtrip_r3_cli.py"
_R3_CLI_HELPER_SHA256 = "62b96a9040d530c8ec592471f0595154fb60239ca03bd6d3b56a6c094dfc7c76"
_FRONT_TRANSPORT_RELATIVE = "backtrader_runtime/certification_simnow_c01_front_transport_v12.py"
_FRONT_TRANSPORT_SHA256 = "f23d1488c29366f040df3bf98fbdc94fc17dc1a58886f269faaf30650d449091"
_FRONT_MODULE_NAME = "backtrader_runtime.certification_simnow_c01_front_transport_v12"
_ROOT_BRIDGE_MODULE_NAME = "backtrader_runtime.certification_simnow_c01_root_v16"
_PROJECTION_MODULE_NAME = "common.c01_root_admission_bridge"
_CERTIFICATION_MODULE_NAME = "common.certification"
_CUSTODY_MODULE_NAME = "backtrader_runtime.certification_simnow_c01_root_custody_v16"
_EXPECTED_SOFTWARE_PINS = {
    "C:/anaconda3/python.exe": "c98caee82c66433f0e89d4abbf152b39a7dc2e99979b28dcb021598b4e3f5642",
    "C:/anaconda3/python311.dll": "162e8557fbed5f39ae24983ee62b2d435b4796c937d9c1a34371888c7e43af00",
}
_ADMISSION_SCHEMA = "simnow.c01.native_td_read_v18.admission.v1"
_ADMISSION_ROOT_NAME = "simnow-c01-native-td-read-v18"
_ADMISSION_COLLECTION_NAME = "admissions"
_ROOT_ONESHOT_NAME = "root-activation-claimed"
_ROOT_ONESHOT_SCHEMA = "simnow.c01.native_td_read_v18.root_activation_claim.v1"
_ROOT_CASE_RECEIPT_NAME = "root-case-receipt.json"
_ROOT_CASE_RECEIPT_TYPE = "C01RootCaseResultReceipt"
_MAX_SOURCE_BYTES = 2 * 1024 * 1024
_MAX_SMALL_BYTES = 256 * 1024
_MAX_ADMISSION_BYTES = 16 * 1024
_MAX_CLI_FRAME_BYTES = 64 * 1024
_MAX_CLI_OUTPUT_BYTES = 8 * 1024 * 1024
_MAX_ROOT_CASE_RECEIPT_BYTES = 64 * 1024
_MAX_PAIR_SELECTION_SECONDS = 30.0
MAX_CLI_SECONDS = 155.0
MAX_CLEANUP_SECONDS = 5.0
_ADMISSION_TTL_SECONDS = 300
_SAFE_REASON = re.compile(r"[a-z0-9_:-]{1,96}\Z")
_SHA256 = re.compile(r"[0-9a-f]{64}\Z")
_ADMISSION_ID = re.compile(r"[0-9a-f]{32}\Z")
_TIME = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z\Z")
_RESULT_KEYS = frozenset(
    {
        "case_id",
        "certification",
        "mode",
        "profile",
        "reason",
        "write_policy",
        "writes",
        "admission_failure_stage",
        "admission_failure_class",
        "worker_observation",
        "post_worker_failure_stage",
        "post_worker_failure_code",
    }
)
_ROOT_CASE_RESULT_KEYS = frozenset(
    {
        "case_id",
        "case_name",
        "status",
        "scenario_id",
        "scenario_name",
        "category",
        "trace_id",
        "started_at",
        "finished_at",
        "duration_seconds",
        "simnow_env",
        "required_events",
        "evidence_fields",
        "pass_conditions",
        "optional",
        "observed_events",
        "missing_required_events",
        "required_events_present",
        "missing_evidence_fields",
        "evidence_fields_present",
        "evidence",
        "failure_reason",
        "next_action",
        "details",
        "audit_events",
    }
)
_ROOT_CHILD_STORED_KEYS = frozenset(
    {
        "case_id",
        "receipt_type",
        "receipt_stored",
        "write_policy",
        "writes",
    }
)
_ROOT_PUBLIC_RESULT_KEYS = frozenset(
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
_POST_WORKER_FAILURE_STAGES = frozenset(
    {"none", "verify_tree", "read_snapshot_artifacts"}
)
_OWNER_VERIFY_TREE_FAILURE_CODES = frozenset(
    {
        "private_tree_depth_limit",
        "private_tree_entry_limit",
        "private_tree_acl_or_identity_invalid",
        "private_run_root_changed",
        "private_evidence_shape_invalid",
        "private_progress_sequence_invalid",
        "private_snapshot_directory_invalid",
        "private_snapshot_shape_invalid",
        "private_evidence_unexpected",
        "private_tree_verification_failed",
    }
)
_OWNER_SNAPSHOT_READ_FAILURE_CODES = frozenset(
    {
        "private_snapshot_size_invalid",
        "private_snapshot_read_failed",
        "private_snapshot_shape_invalid",
    }
)
_POST_WORKER_FAILURE_CODES = frozenset(
    {"none", "unclassified_owner_error"}
) | _OWNER_VERIFY_TREE_FAILURE_CODES | _OWNER_SNAPSHOT_READ_FAILURE_CODES
_ADMISSION_FAILURE_STAGES = frozenset(
    {
        "none",
        "helper_load",
        "helper_registration",
        "known_folder",
        "issuer_source_lock",
        "runner_source_lock",
        "namespace_lock",
        "namespace_scan",
        "admission_read_parse",
        "profile_claim_create",
        "consumed_marker_create",
        "admitted_profile_body",
        "lease_revalidation",
        "source_handle_close",
    }
)
_ADMISSION_FAILURE_CLASSES = frozenset(
    {"none", "permission", "os", "type_value", "runtime", "other"}
)
_EXPECTED_SOURCE_POLICY = {
    "profile_id": PROFILE_ID,
    "issuer_source_sha256": _V18_SHA256,
    "source_manifest_sha256": _V18_MANIFEST_SHA256,
    "admission_schema_sha256": _V18_SCHEMA_SHA256,
    "case_runner_source_sha256": _CASE_RUNNER_SHA256,
    "front_transport_source_sha256": _FRONT_TRANSPORT_SHA256,
}
_REQUIRED_BINDING_NAMES = frozenset(
    {
        "case_runner_source_sha256",
        "issuer_source_sha256",
        "source_manifest_sha256",
        "profile_contract_sha256",
        "owner_source_sha256",
        "worker_source_sha256",
        "protocol_source_sha256",
        "contract_source_sha256",
        "supervisor_source_sha256",
        "sdk_dependency_manifest_sha256",
        "interpreter_binding_source_sha256",
        "case_contract_sha256",
        "case_strategy_sha256",
        "envref_template_sha256",
    }
)

# Keep any Job handles that could not be proven closed alive until this
# one-shot Root process exits. This is deliberately private and never emitted.
_ROOT_RETAINED_UNRESOLVED_JOB_REFS: list[tuple[Any, ...]] = []


class RootActivationError(RuntimeError):
    """A redacted fixed-category failure from the V18 Root entry."""

    def __init__(self, reason: str):
        if type(reason) is not str or not _SAFE_REASON.fullmatch(reason):
            reason = "root_activation_blocked"
        self.reason = reason
        super().__init__(reason)


@dataclass(frozen=True)
class _ActivationOutput:
    value: Optional[dict[str, object]] = None
    exit_code: int = 2


@dataclass
class _PipeCapture:
    stream: Any
    maximum: int = _MAX_CLI_OUTPUT_BYTES
    data: bytearray = dataclass_field(default_factory=bytearray)
    data_lock: Any = dataclass_field(default_factory=threading.Lock, repr=False)
    eof: bool = False
    overflow: bool = False
    failed: bool = False
    closed: bool = False
    thread: Optional[threading.Thread] = None


def _sha256(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _canonical_json(value: object) -> bytes:
    return (
        json.dumps(value, ensure_ascii=True, allow_nan=False, sort_keys=True, separators=(",", ":"))
        + "\n"
    ).encode("ascii")


def _canonical_json_value(value: object) -> bytes:
    return json.dumps(
        value, ensure_ascii=True, allow_nan=False, sort_keys=True, separators=(",", ":")
    ).encode("ascii")


def _strict_pairs(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate_key")
        result[key] = value
    return result


def _parse_json(raw: bytes, maximum: int) -> object:
    if type(raw) is not bytes or not 0 < len(raw) <= maximum:
        raise ValueError("json_size_invalid")
    return json.loads(
        raw.decode("ascii"),
        object_pairs_hook=_strict_pairs,
        parse_constant=lambda _item: (_ for _ in ()).throw(ValueError("nonfinite_json")),
    )


def _blocked(
    reason: str,
    *,
    admission_failure_stage: str = "none",
    admission_failure_class: str = "none",
) -> dict[str, object]:
    safe = reason if type(reason) is str and _SAFE_REASON.fullmatch(reason) else "root_activation_blocked"
    if (
        type(admission_failure_stage) is not str
        or admission_failure_stage not in _ADMISSION_FAILURE_STAGES
        or type(admission_failure_class) is not str
        or admission_failure_class not in _ADMISSION_FAILURE_CLASSES
        or ((admission_failure_stage == "none") != (admission_failure_class == "none"))
    ):
        admission_failure_stage = "none"
        admission_failure_class = "none"
    return {
        "case_id": CASE_ID,
        "certification": "BLOCKED",
        "mode": PROFILE_ID,
        "profile": PROFILE_ID,
        "reason": safe,
        "write_policy": "NO_WRITE",
        "writes": 0,
        "admission_failure_stage": admission_failure_stage,
        "admission_failure_class": admission_failure_class,
        "worker_observation": None,
        "post_worker_failure_stage": "none",
        "post_worker_failure_code": "none",
    }


def _public_blocked(
    reason: str, lifecycle: Optional[Mapping[str, object]] = None
) -> dict[str, object]:
    safe = reason if type(reason) is str and _SAFE_REASON.fullmatch(reason) else "root_activation_blocked"
    observed = _valid_lifecycle(lifecycle)
    return {
        "case_id": CASE_ID,
        "certification": "BLOCKED",
        "mode": PROFILE_ID,
        "profile": PROFILE_ID,
        "reason": safe,
        "write_policy": "NO_WRITE",
        "writes": 0,
        "receipt_type": None,
        "receipt_verified": False,
        "source_closure_verified": False,
        "root_postverify_verified": False,
        "request_count": 0,
        "query_callback_count": 0,
        "snapshot_count": 0,
        "write_invocation_count": 0,
        "outer_job_empty": lifecycle["job_active_zero"] if observed else False,
        "stdout_eof": lifecycle["stdout_eof"] if observed else False,
        "stderr_eof": lifecycle["stderr_eof"] if observed else False,
        "stderr_empty": lifecycle["stderr_empty"] if observed else False,
        "job_handles_closed": lifecycle["handles_closed"] if observed else False,
        "reader_threads_joined": lifecycle["reader_threads_joined"] if observed else False,
        "cleanup_verified": (
            bool(observed)
            and lifecycle["job_active_zero"]
            and lifecycle["stdout_eof"]
            and lifecycle["stderr_eof"]
            and lifecycle["stderr_empty"]
            and lifecycle["handles_closed"]
            and lifecycle["reader_threads_joined"]
            and lifecycle["forced_termination"] is False
        ),
    }


def _root_pass_projection(query_callback_count: int, lifecycle: Mapping[str, object]) -> dict[str, object]:
    if (
        type(query_callback_count) is not int
        or not 6 <= query_callback_count <= 8
        or not _valid_lifecycle(lifecycle)
        or lifecycle["normal_exit_code"] != 0
    ):
        raise RootActivationError("root_public_projection_invalid")
    return {
        "case_id": CASE_ID,
        "certification": "PASS",
        "mode": PROFILE_ID,
        "profile": PROFILE_ID,
        "reason": "root_case_receipt_verified",
        "write_policy": "NO_WRITE",
        "writes": 0,
        "receipt_type": _ROOT_CASE_RECEIPT_TYPE,
        "receipt_verified": True,
        "source_closure_verified": True,
        "root_postverify_verified": True,
        "request_count": 8,
        "query_callback_count": query_callback_count,
        "snapshot_count": 2,
        "write_invocation_count": 0,
        "outer_job_empty": lifecycle["job_active_zero"],
        "stdout_eof": lifecycle["stdout_eof"],
        "stderr_eof": lifecycle["stderr_eof"],
        "stderr_empty": lifecycle["stderr_empty"],
        "job_handles_closed": lifecycle["handles_closed"],
        "reader_threads_joined": lifecycle["reader_threads_joined"],
        "cleanup_verified": (
            lifecycle["job_active_zero"]
            and lifecycle["stdout_eof"]
            and lifecycle["stderr_eof"]
            and lifecycle["stderr_empty"]
            and lifecycle["handles_closed"]
            and lifecycle["reader_threads_joined"]
            and lifecycle["forced_termination"] is False
        ),
    }


def _emit(result: Mapping[str, object], *, exit_code: Optional[int] = None) -> int:
    print(_canonical_json_value(dict(result)).decode("ascii"))
    if type(exit_code) is int and exit_code in (0, 2):
        return exit_code
    return 0 if result.get("certification") == "PASS" else 2


def _write_output(output: _ActivationOutput) -> int:
    if type(output) is not _ActivationOutput or output.exit_code not in (0, 2):
        output = _ActivationOutput(value=_blocked("root_activation_blocked"), exit_code=2)
    value = output.value if type(output.value) is dict else _blocked("root_activation_blocked")
    return _emit(value, exit_code=output.exit_code)


def _read_own_source() -> bytes:
    path = Path(__file__).absolute()
    try:
        if path.is_symlink() or not path.is_file():
            raise ValueError
        with path.open("rb") as stream:
            raw = stream.read(_MAX_SOURCE_BYTES + 1)
    except Exception:
        raise RootActivationError("root_source_unavailable") from None
    if not 0 < len(raw) <= _MAX_SOURCE_BYTES:
        raise RootActivationError("root_source_size_invalid")
    return raw


def _parse_activation_args(argv: object, own_source: bytes) -> str:
    if type(argv) not in (list, tuple) or len(argv) != 3:
        raise RootActivationError("root_confirmation_required")
    if argv[0] != "--activate-c01-v18-td-read" or argv[1] != "--expected-wrapper-sha256":
        raise RootActivationError("root_confirmation_required")
    expected = argv[2]
    if type(expected) is not str or not _SHA256.fullmatch(expected):
        raise RootActivationError("root_source_pin_invalid")
    if _sha256(own_source) != expected:
        raise RootActivationError("root_source_pin_mismatch")
    return expected


def _parse_root_child_args(argv: object, own_source: bytes) -> tuple[str, str, str]:
    if type(argv) not in (list, tuple) or len(argv) != 7:
        raise RootActivationError("root_child_activation_invalid")
    if argv[0] != "--root-child-v18" or argv[1] != "--expected-wrapper-sha256":
        raise RootActivationError("root_child_activation_invalid")
    if argv[3] != "--expected-entry-sha256":
        raise RootActivationError("root_child_activation_invalid")
    if argv[5] != "--root-case-receipt-admission-id":
        raise RootActivationError("root_child_activation_invalid")
    wrapper_sha256, entry_sha256 = argv[2], argv[4]
    if (
        type(wrapper_sha256) is not str
        or not _SHA256.fullmatch(wrapper_sha256)
        or _sha256(own_source) != wrapper_sha256
        or type(entry_sha256) is not str
        or entry_sha256 != _ROOT_ENTRY_SHA256
        or type(argv[6]) is not str
        or not _ADMISSION_ID.fullmatch(argv[6])
    ):
        raise RootActivationError("root_child_source_pin_mismatch")
    return wrapper_sha256, entry_sha256, argv[6]


def _read_pinned_public_file(root: Path, relative: str, expected: str, maximum: int) -> bytes:
    path = root / Path(relative)
    try:
        info = path.lstat()
        if (
            path.is_symlink()
            or getattr(info, "st_file_attributes", 0) & 0x400
            or not path.is_absolute()
            or not path.is_file()
            or not 0 < info.st_size <= maximum
        ):
            raise ValueError
        with path.open("rb") as stream:
            raw = stream.read(maximum + 1)
    except Exception:
        raise RootActivationError("pinned_public_source_unavailable") from None
    if len(raw) > maximum or len(raw) != info.st_size or _sha256(raw) != expected:
        raise RootActivationError("pinned_public_source_mismatch")
    return raw


def _entry_source_maps(raw: bytes) -> tuple[dict[str, str], dict[str, str]]:
    if type(raw) is not bytes or not raw:
        raise RootActivationError("root_entry_source_invalid")
    try:
        tree = ast.parse(raw.decode("utf-8"))
        maps: dict[str, object] = {}
        for node in tree.body:
            if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
                if node.target.id in {"_EXACT_PUBLIC_SOURCE_PINS", "_EXACT_SOFTWARE_PINS"}:
                    maps[node.target.id] = ast.literal_eval(node.value)
        public = maps.get("_EXACT_PUBLIC_SOURCE_PINS")
        software = maps.get("_EXACT_SOFTWARE_PINS")
    except Exception:
        raise RootActivationError("root_entry_source_invalid") from None
    if (
        type(public) is not dict
        or _ROOT_ENTRY_RELATIVE in public
        or type(software) is not dict
        or software != _EXPECTED_SOFTWARE_PINS
        or any(
            type(path) is not str
            or not path
            or "\\" in path
            or type(digest) is not str
            or not _SHA256.fullmatch(digest)
            for path, digest in public.items()
        )
        or len(public) != 27
    ):
        raise RootActivationError("root_entry_source_map_invalid")
    return dict(public), dict(software)


def _verify_entry_public_closure(
    root: Path, entry_raw: bytes
) -> tuple[dict[str, str], dict[str, str], dict[str, str]]:
    public_pins, software_pins = _entry_source_maps(entry_raw)
    complete = dict(public_pins)
    complete[_ROOT_ENTRY_RELATIVE] = _sha256(entry_raw)
    if complete[_ROOT_ENTRY_RELATIVE] != _ROOT_ENTRY_SHA256:
        raise RootActivationError("root_entry_source_pin_mismatch")
    for relative, digest in public_pins.items():
        _read_pinned_public_file(root, relative, digest, _MAX_SOURCE_BYTES)
    return public_pins, software_pins, complete


def _load_child_source_module(
    root: Path,
    *,
    name: str,
    relative: str,
    digest: str,
    raw: bytes,
) -> ModuleType:
    if (
        type(name) is not str
        or type(relative) is not str
        or type(digest) is not str
        or not _SHA256.fullmatch(digest)
        or type(raw) is not bytes
        or _sha256(raw) != digest
        or name in sys.modules
    ):
        raise RootActivationError("root_source_module_binding_invalid")
    path = (root / Path(relative)).resolve(strict=True)
    module = ModuleType(name)
    module.__file__ = str(path)
    module.__package__ = name.rpartition(".")[0]
    module.__loader__ = None
    module.__spec__ = importlib.machinery.ModuleSpec(name, loader=None)
    module.__c01_source_sha256__ = digest
    sys.modules[name] = module
    try:
        code = compile(raw, module.__file__, "exec", dont_inherit=True)
        exec(code, module.__dict__)
    except Exception:
        if sys.modules.get(name) is module:
            sys.modules.pop(name, None)
        raise RootActivationError("root_source_module_compile_failed") from None
    return module


def _load_root_entry_modules(
    root: Path,
    entry_raw: bytes,
    public_pins: Mapping[str, str],
    software_pins: Mapping[str, str],
) -> tuple[dict[str, ModuleType], tuple[tuple[str, ModuleType], ...]]:
    if type(public_pins) is not dict or type(software_pins) is not dict:
        raise RootActivationError("root_source_map_invalid")
    expected_names = (
        (_FRONT_MODULE_NAME, _FRONT_TRANSPORT_RELATIVE),
        (_ROOT_BRIDGE_MODULE_NAME, "backtrader_runtime/certification_simnow_c01_root_v16.py"),
        (_PROJECTION_MODULE_NAME, "examples/000_live_certification/simnow_penetration/common/c01_root_admission_bridge.py"),
        (_CERTIFICATION_MODULE_NAME, "examples/000_live_certification/simnow_penetration/common/certification.py"),
        (_CUSTODY_MODULE_NAME, "backtrader_runtime/certification_simnow_c01_root_custody_v16.py"),
        ("backtrader_runtime.certification_simnow_c01_root_entry_v18", _ROOT_ENTRY_RELATIVE),
        (
            "_c01_v18_root_receipt_private_writer",
            "backtrader_runtime/certification_roundtrip_private.py",
        ),
        (
            "_c01_v18_root_receipt_cli_writer",
            "backtrader_runtime/certification_binance_roundtrip_r3_cli.py",
        ),
    )
    loaded: list[tuple[str, ModuleType]] = []
    modules: dict[str, ModuleType] = {}
    try:
        for name, relative in expected_names:
            digest = _ROOT_ENTRY_SHA256 if relative == _ROOT_ENTRY_RELATIVE else public_pins.get(relative)
            if type(digest) is not str or not _SHA256.fullmatch(digest):
                raise RootActivationError("root_source_map_invalid")
            raw = entry_raw if relative == _ROOT_ENTRY_RELATIVE else _read_pinned_public_file(
                root, relative, digest, _MAX_SOURCE_BYTES
            )
            module = _load_child_source_module(
                root, name=name, relative=relative, digest=digest, raw=raw
            )
            loaded.append((name, module))
            modules[name] = module
        if software_pins != _EXPECTED_SOFTWARE_PINS:
            raise RootActivationError("runtime_source_map_invalid")
        return modules, tuple(loaded)
    except Exception:
        _unload_root_entry_modules(tuple(loaded))
        raise


def _unload_root_entry_modules(loaded: tuple[tuple[str, ModuleType], ...]) -> None:
    for name, module in reversed(loaded):
        if sys.modules.get(name) is module:
            sys.modules.pop(name, None)


def _run_root_entry_child(
    *, wrapper_sha256: str, entry_sha256: str, admission_id: str
) -> _ActivationOutput:
    loaded: tuple[tuple[str, ModuleType], ...] = ()
    try:
        root = REPO_ROOT.resolve(strict=True)
        if Path(__file__).resolve(strict=True) != (root / Path(_ENTRY_RELATIVE)).resolve(strict=True):
            raise RootActivationError("root_source_path_mismatch")
        own_source = _read_own_source()
        if (
            _sha256(own_source) != wrapper_sha256
            or entry_sha256 != _ROOT_ENTRY_SHA256
            or type(admission_id) is not str
            or not _ADMISSION_ID.fullmatch(admission_id)
        ):
            raise RootActivationError("root_source_pin_mismatch")
        entry_raw = _read_pinned_public_file(
            root, _ROOT_ENTRY_RELATIVE, entry_sha256, _MAX_SOURCE_BYTES
        )
        public_pins, software_pins, complete_pins = _verify_entry_public_closure(root, entry_raw)
        modules, loaded = _load_root_entry_modules(root, entry_raw, public_pins, software_pins)
        entry_module = modules["backtrader_runtime.certification_simnow_c01_root_entry_v18"]
        receipt = entry_module.run_c01_root_entry_v18(
            root=root,
            front_module=modules[_FRONT_MODULE_NAME],
            root_bridge_module=modules[_ROOT_BRIDGE_MODULE_NAME],
            projection_module=modules[_PROJECTION_MODULE_NAME],
            certification_module=modules[_CERTIFICATION_MODULE_NAME],
            root_custody_module=modules[_CUSTODY_MODULE_NAME],
            exact_public_pins=complete_pins,
            exact_software_pins=software_pins,
        )
        bridge = modules[_ROOT_BRIDGE_MODULE_NAME]
        receipt_type = getattr(bridge, "C01RootCaseResultReceipt", None)
        if (
            type(receipt_type) is not type
            or type(receipt) is not receipt_type
            or receipt.exit_code() != 0
        ):
            raise RootActivationError("root_case_receipt_invalid")
        # The entry returns only after the issuer ExitStack, Root scope,
        # producer source/runtime lease and front source bundle all close.
        # Keep the full receipt in a protected artifact; child stdout carries
        # only a fixed storage marker for the outer Job supervisor.
        payload = _canonical_json(receipt.to_dict())
        _validate_root_case_receipt(payload)
        _store_private_root_case_receipt(
            root=root,
            admission_id=admission_id,
            payload=payload,
            private_module=modules["_c01_v18_root_receipt_private_writer"],
            cli_module=modules["_c01_v18_root_receipt_cli_writer"],
        )
        return _ActivationOutput(
            value={
                "case_id": CASE_ID,
                "receipt_type": _ROOT_CASE_RECEIPT_TYPE,
                "receipt_stored": True,
                "write_policy": "NO_WRITE",
                "writes": 0,
            },
            exit_code=0,
        )
    except RootActivationError as error:
        return _ActivationOutput(value=_blocked(error.reason), exit_code=2)
    except Exception:
        return _ActivationOutput(value=_blocked("root_entry_blocked"), exit_code=2)
    finally:
        _unload_root_entry_modules(loaded)


@contextmanager
def _verified_v18_sources(root: Path):
    """Open the independently reviewed V18/front transport public closure."""

    if not isinstance(root, Path) or root.resolve(strict=True) != REPO_ROOT.resolve(strict=True):
        raise RootActivationError("repository_root_mismatch")
    entry_raw = _read_pinned_public_file(
        root, _ROOT_ENTRY_RELATIVE, _ROOT_ENTRY_SHA256, _MAX_SOURCE_BYTES
    )
    public_pins, software_pins, complete_pins = _verify_entry_public_closure(root, entry_raw)
    front_raw = _read_pinned_public_file(
        root, _FRONT_TRANSPORT_RELATIVE, _FRONT_TRANSPORT_SHA256, _MAX_SOURCE_BYTES
    )
    runner_raw = _read_pinned_public_file(
        root, _CASE_RUNNER_RELATIVE, _CASE_RUNNER_SHA256, _MAX_SOURCE_BYTES
    )
    _read_pinned_public_file(root, _V18_MANIFEST_RELATIVE, _V18_MANIFEST_SHA256, _MAX_SMALL_BYTES)
    _read_pinned_public_file(root, _V18_SCHEMA_RELATIVE, _V18_SCHEMA_SHA256, _MAX_SMALL_BYTES)
    module = ModuleType(_FRONT_MODULE_NAME)
    module.__file__ = str(root / Path(_FRONT_TRANSPORT_RELATIVE))
    module.__package__ = "backtrader_runtime"
    module.__c01_source_sha256__ = _FRONT_TRANSPORT_SHA256
    if _FRONT_MODULE_NAME in __import__("sys").modules:
        raise RootActivationError("front_source_already_loaded")
    __import__("sys").modules[_FRONT_MODULE_NAME] = module
    bundle_context = None
    try:
        exec(compile(front_raw, module.__file__, "exec", dont_inherit=True), module.__dict__)
        bundle_context = module.verified_c01_v18_sources(root)
        bundle = bundle_context.__enter__()
        source_policy = dict(_EXPECTED_SOURCE_POLICY)
        if (
            type(bundle) is not module.VerifiedC01V18SourceBundle
            or bundle._active is not True
            or bundle.issuer.PROFILE_ID != PROFILE_ID
            or bundle.issuer.__c01_source_sha256__ != _V18_SHA256
            or _sha256(runner_raw) != _CASE_RUNNER_SHA256
        ):
            raise RootActivationError("v18_source_policy_mismatch")
        yield bundle, source_policy, runner_raw, entry_raw, public_pins, software_pins, complete_pins
    except RootActivationError:
        raise
    except Exception:
        raise RootActivationError("v18_source_bundle_unavailable") from None
    finally:
        if bundle_context is not None:
            try:
                bundle_context.__exit__(None, None, None)
            except Exception:
                pass
        if __import__("sys").modules.get(_FRONT_MODULE_NAME) is module:
            __import__("sys").modules.pop(_FRONT_MODULE_NAME, None)


def _validate_source_policy(value: object) -> dict[str, str]:
    if type(value) is not dict or value != _EXPECTED_SOURCE_POLICY:
        raise RootActivationError("v18_source_policy_mismatch")
    return dict(value)


def _build_admission_document(
    *,
    admission_id: str,
    required_bindings: Mapping[str, str],
    configured_pair_count: int,
    config_sha256: str,
    account_scope_sha256: str,
    credential_binding_sha256: str,
    now: datetime,
) -> bytes:
    if (
        type(admission_id) is not str
        or not _ADMISSION_ID.fullmatch(admission_id)
        or type(configured_pair_count) is not int
        or not 1 <= configured_pair_count <= 8
        or now.tzinfo is None
        or now.utcoffset() != timedelta(0)
    ):
        raise RootActivationError("admission_binding_invalid")
    bindings = dict(required_bindings)
    bindings.update(
        config_source_sha256=config_sha256,
        account_scope_sha256=account_scope_sha256,
        credential_binding_sha256=credential_binding_sha256,
    )
    if (
        set(required_bindings) != _REQUIRED_BINDING_NAMES
        or set(bindings)
        != _REQUIRED_BINDING_NAMES
        | {"config_source_sha256", "account_scope_sha256", "credential_binding_sha256"}
        or any(type(item) is not str or not _SHA256.fullmatch(item) for item in bindings.values())
    ):
        raise RootActivationError("admission_binding_invalid")
    start = now.replace(microsecond=0) - timedelta(seconds=1)
    end = start + timedelta(seconds=_ADMISSION_TTL_SECONDS)
    scope = {
        "role": "READ_ONLY_NATIVE_TD_NO_JOIN",
        "case_id": CASE_ID,
        "environment": "simulation",
        "operation_scope": "TD_AUTH_LOGIN_ORDERS_POSITIONS_FUNDS_BASELINE_FINAL",
        "front_transport_probe": True,
        "max_front_pair_candidates": 8,
        "md_sdk_session": False,
        "market_data_subscribe": False,
        "native_join": False,
        "order_insert": False,
        "order_cancel": False,
        "max_order_insert_requests": 0,
        "max_order_cancel_requests": 0,
        "configured_front_pair_count": configured_pair_count,
    }
    value = {
        "schema": _ADMISSION_SCHEMA,
        "profile_id": PROFILE_ID,
        "case_id": CASE_ID,
        "admission_id": admission_id,
        "status": "ACTIVE",
        "not_before_utc": start.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "expires_at_utc": end.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "scope": scope,
        "bindings": bindings,
    }
    raw = _canonical_json(value)
    if len(raw) > _MAX_ADMISSION_BYTES:
        raise RootActivationError("admission_size_invalid")
    return raw


_WORKER_OBSERVATION_SCHEMA = "simnow.c01.worker-observation.v2"
_WORKER_FAILURE_DIAGNOSTIC_SCHEMA = "simnow.c01.worker-failure-diagnostic.v1"
_POSITION_TEXT_PROBE_SCHEMA = "simnow.c01.position_text_shape_probe.v1"
_POSITION_TEXT_FAILURE_ORDINAL = 119
_POSITION_TEXT_PROBE_FIELDS = MappingProxyType(
    {
        "positions": MappingProxyType(
            {
                1: "ExchangeID",
                2: "InstrumentID",
                3: "PosiDirection",
                4: "HedgeFlag",
                5: "PositionDate",
                6: "BrokerID",
                7: "InvestorID",
                8: "TradingDay",
                9: "InvestUnitID",
                10: "reserve1",
            }
        ),
        "funds": MappingProxyType(
            {
                1: "BrokerID",
                2: "AccountID",
                3: "CurrencyID",
                4: "BizType",
                5: "TradingDay",
            }
        ),
    }
)
_POSITION_TEXT_PROBE_TYPES = frozenset({"str", "bytes", "int", "float", "null", "other"})
_POSITION_TEXT_PROBE_CATEGORIES = frozenset(
    {
        "EMPTY",
        "NUL_ONLY",
        "CONTROL",
        "ASCII_DECODE",
        "WHITESPACE",
        "TOO_LONG",
        "TYPE",
        "MISSING",
        "UNOBSERVED",
    }
)
_WORKER_OBSERVATION_SUPERVISOR_REASONS = frozenset(
    {
        "candidate_transport_complete",
        "diagnostic_intent_stream_invalid",
        "diagnostic_profile_only",
        "launch_packet_invalid",
        "native_close_unknown",
        "process_complete",
        "runtime_bound_invalid",
        "supervisor_internal_error",
        "windows_required",
        "worker_exit_nonzero",
        "worker_frame_invalid",
        "worker_frame_misbinding",
        "worker_incomplete",
        "worker_job_accounting_unknown",
        "worker_job_create_failed",
        "worker_output_limit_exceeded",
        "worker_output_read_failed",
        "worker_pid_unavailable",
        "worker_pipe_setup_failed",
        "worker_process_creation_unobserved",
        "worker_resume_failed",
        "worker_running",
        "worker_setup_failed",
        "worker_source_changed_before_resume",
        "worker_source_unavailable",
        "worker_stderr_unexpected",
        "worker_stdin_incomplete",
        "worker_stdin_write_failed",
        "worker_supervisor_failed",
        "job_assignment_unobserved",
        "approved_interpreter_binding_required",
        "runtime_deadline_exceeded",
        "worker_pin_invalid",
        "account_binding_invalid",
        "worker_process_incomplete",
        "worker_result_invalid",
    }
)
_WORKER_OBSERVATION_STAGE_EVENTS = {
    "worker": {"begin"},
    "private_paths": {"end"},
    "sdk_install_verify": {"begin", "end"},
    "sdk_import": {"begin", "end"},
    "client_construct": {"begin", "end"},
    "client_start": {"begin", "end"},
    "client_no_join_start_policy": {"begin", "end", "failed"},
    "client_start_native_module_check": {"begin", "end", "failed"},
    "client_start_generation_reserve": {"begin", "end", "failed"},
    "client_start_identity_validate": {"begin", "end", "failed"},
    "client_start_identity_compare": {"begin", "end", "failed"},
    "client_start_flow_prepare": {"begin", "end", "failed"},
    "native_create_trader_api": {"begin", "end", "failed"},
    "native_register_spi_attach": {"begin", "end", "failed"},
    "native_subscribe_private_topic": {"begin", "end", "failed"},
    "native_subscribe_public_topic": {"begin", "end", "failed"},
    "native_register_front": {"begin", "end", "failed"},
    "native_api_init": {"begin", "end", "failed"},
    "native_register_spi_detach": {"begin", "end", "failed"},
    "native_release": {"begin", "end", "failed"},
    "login_wait": {"begin", "end"},
    "snapshot_directory": {"begin", "end"},
    "authenticate_request": {"begin", "end"},
    "login_request": {"begin", "end"},
    "authenticate_callback": {"callback_first", "callback_terminal"},
    "login_callback": {"callback_first", "callback_terminal"},
    "baseline_orders_request": {"begin", "end"},
    "baseline_positions_request": {"begin", "end"},
    "baseline_funds_request": {"begin", "end"},
    "final_orders_request": {"begin", "end"},
    "final_positions_request": {"begin", "end"},
    "final_funds_request": {"begin", "end"},
    "baseline_orders_callback": {"callback_first", "callback_terminal"},
    "baseline_positions_callback": {"callback_first", "callback_terminal"},
    "baseline_funds_callback": {"callback_first", "callback_terminal"},
    "final_orders_callback": {"callback_first", "callback_terminal"},
    "final_positions_callback": {"callback_first", "callback_terminal"},
    "final_funds_callback": {"callback_first", "callback_terminal"},
    "baseline_orders_read": {"begin", "end"},
    "baseline_positions_read": {"begin", "end"},
    "baseline_funds_read": {"begin", "end"},
    "final_orders_read": {"begin", "end"},
    "final_positions_read": {"begin", "end"},
    "final_funds_read": {"begin", "end"},
    "baseline_snapshot_write": {"begin", "end"},
    "final_snapshot_write": {"begin", "end"},
    "native_stop": {"begin", "end", "failed"},
    "worker_receipt": {"begin", "end"},
}
_WORKER_OBSERVATION_COUNT_LIMITS = {
    "authenticate_attempts": 1,
    "authenticate_return_code_observed": 1,
    "authenticate_return_code_zero": 1,
    "authenticate_callback_first": 1,
    "authenticate_callback_terminal": 1,
    "login_attempts": 1,
    "login_return_code_observed": 1,
    "login_return_code_zero": 1,
    "login_callback_first": 1,
    "login_callback_terminal": 1,
    "query_attempts": 6,
    "query_return_code_observed": 6,
    "query_return_code_zero": 6,
    "query_callback_first": 6,
    "query_callback_terminal": 6,
    "order_insert_requests": 1_000_000,
    "order_cancel_requests": 1_000_000,
}
_WORKER_OBSERVATION_REQUIRED_REASONS = frozenset(
    {
        "worker_process_incomplete",
        "native_close_unknown",
        "worker_progress_invalid",
        "worker_receipt_misbinding",
        "diagnostic_profile_only",
        "diagnostic_intent_stream_invalid",
    }
)


def _valid_worker_observation(value: object) -> bool:
    if value is None:
        return True
    required = {
        "schema",
        "authority",
        "supervisor_result_type",
        "supervisor_reason",
        "supervisor_status",
        "lifecycle_type",
        "receipt_type",
        "lifecycle",
        "progress",
        "request_counts",
        "failure_diagnostic",
        "write_policy",
        "writes",
    }
    lifecycle_required = {
        "assignment_before_resume",
        "stdin_fully_sent",
        "stdout_eof",
        "stderr_eof",
        "process_exit_observed",
        "process_exit_code",
        "job_active_status",
        "handles_closed",
        "timed_out",
        "forced_kill",
        "containment",
        "status",
    }
    progress_required = {"status", "last_stage", "last_event", "record_count"}
    failure_required = {
        "schema",
        "status",
        "failure_code_ordinal",
        "request_count",
        "callback_count",
        "auth_login_callback_row_count",
        "query_request_count",
        "query_event_count",
        "baseline_query_callback_count",
        "final_query_callback_count",
        "snapshot_count",
        "baseline_snapshot_count",
        "final_snapshot_count",
        "order_insert_requests",
        "order_cancel_requests",
        "native_close_status",
        "position_text_probe",
    }
    if (
        type(value) is not dict
        or set(value) != required
        or value.get("schema") != _WORKER_OBSERVATION_SCHEMA
        or value.get("authority") != "NONE"
        or value.get("supervisor_result_type") not in {"expected", "unexpected", "unobserved"}
        or value.get("supervisor_reason")
        not in (_WORKER_OBSERVATION_SUPERVISOR_REASONS | {"UNKNOWN", "UNOBSERVED"})
        or value.get("supervisor_status") not in {"BLOCKED", "UNKNOWN", "UNOBSERVED"}
        or value.get("lifecycle_type") not in {"expected", "unexpected", "unobserved"}
        or value.get("receipt_type") not in {"expected", "none", "invalid", "unexpected", "unobserved"}
        or value.get("write_policy") != "NO_WRITE"
        or type(value.get("writes")) is not int
        or value.get("writes") != 0
    ):
        return False
    lifecycle = value.get("lifecycle")
    progress = value.get("progress")
    counts = value.get("request_counts")
    if (
        type(lifecycle) is not dict
        or set(lifecycle) != lifecycle_required
        or type(progress) is not dict
        or set(progress) != progress_required
        or type(counts) is not dict
        or set(counts) != set(_WORKER_OBSERVATION_COUNT_LIMITS)
    ):
        return False
    failure = value.get("failure_diagnostic")
    if (
        type(failure) is not dict
        or set(failure) != failure_required
        or failure.get("schema") != _WORKER_FAILURE_DIAGNOSTIC_SCHEMA
        or failure.get("status") not in {"verified", "UNOBSERVED"}
        or failure.get("native_close_status") not in {"present", "absent", "UNOBSERVED"}
    ):
        return False
    text_probe = failure.get("position_text_probe")
    if (
        type(text_probe) is not dict
        or set(text_probe)
        != {"schema", "family", "field_ordinal", "field", "type_bucket", "invalid_category"}
        or text_probe.get("schema") != _POSITION_TEXT_PROBE_SCHEMA
        or type(text_probe.get("invalid_category")) is not str
        or text_probe.get("invalid_category") not in _POSITION_TEXT_PROBE_CATEGORIES
    ):
        return False
    if text_probe["invalid_category"] == "UNOBSERVED":
        if any(text_probe.get(name) is not None for name in ("family", "field_ordinal", "field", "type_bucket")):
            return False
    else:
        family = text_probe.get("family")
        ordinal = text_probe.get("field_ordinal")
        if (
            type(family) is not str
            or family not in _POSITION_TEXT_PROBE_FIELDS
            or type(ordinal) is not int
            or text_probe.get("field") != _POSITION_TEXT_PROBE_FIELDS[family].get(ordinal)
            or type(text_probe.get("type_bucket")) is not str
            or text_probe.get("type_bucket") not in _POSITION_TEXT_PROBE_TYPES
        ):
            return False
        if failure.get("failure_code_ordinal") != _POSITION_TEXT_FAILURE_ORDINAL:
            return False
    failure_limits = {
        "failure_code_ordinal": 207,
        "request_count": 8,
        "callback_count": 10000,
        "auth_login_callback_row_count": 10000,
        "query_request_count": 6,
        "query_event_count": 10000,
        "baseline_query_callback_count": 10000,
        "final_query_callback_count": 10000,
        "snapshot_count": 2,
        "baseline_snapshot_count": 1,
        "final_snapshot_count": 1,
        "order_insert_requests": 1000000,
        "order_cancel_requests": 1000000,
    }
    for name, maximum in failure_limits.items():
        count = failure.get(name)
        if count is not None and (type(count) is not int or not 0 <= count <= maximum):
            return False
    if failure["status"] == "UNOBSERVED":
        if any(failure.get(name) is not None for name in failure_limits) or failure[
            "native_close_status"
        ] != "UNOBSERVED" or text_probe["invalid_category"] != "UNOBSERVED":
            return False
    elif (
        any(
            failure.get(name) is None
            for name in failure_limits
            if name not in {"order_insert_requests", "order_cancel_requests"}
        )
        or failure["native_close_status"] not in {"present", "absent"}
        or failure["baseline_snapshot_count"] + failure["final_snapshot_count"]
        != failure["snapshot_count"]
        or failure["baseline_query_callback_count"]
        + failure["final_query_callback_count"]
        != failure["query_event_count"]
        or failure["query_request_count"] > failure["request_count"]
    ):
        return False
    for name in (
        "assignment_before_resume",
        "stdin_fully_sent",
        "stdout_eof",
        "stderr_eof",
        "process_exit_observed",
        "handles_closed",
        "timed_out",
        "forced_kill",
    ):
        if lifecycle[name] is not None and type(lifecycle[name]) is not bool:
            return False
    if lifecycle["process_exit_code"] not in {
        "ZERO", "TWO", "OTHER_NONZERO", "UNOBSERVED", "INVALID"
    }:
        return False
    if lifecycle["job_active_status"] not in {"ZERO", "NONZERO", "UNOBSERVED", "INVALID"}:
        return False
    if lifecycle["containment"] not in {
        "windows_job", "not_started", "other", "UNKNOWN", "UNOBSERVED"
    } or lifecycle["status"] not in {"BLOCKED", "UNKNOWN", "UNOBSERVED"}:
        return False
    progress_status = progress.get("status")
    if progress_status not in {"verified", "missing", "invalid", "unavailable", "UNOBSERVED"}:
        return False
    if progress_status == "UNOBSERVED":
        if any(progress.get(name) is not None for name in ("last_stage", "last_event", "record_count")):
            return False
    elif (
        type(progress.get("record_count")) is not int
        or not 0 <= progress["record_count"] <= 128
    ):
        return False
    elif progress_status == "verified":
        stage = progress.get("last_stage")
        event = progress.get("last_event")
        if (
            progress["record_count"] < 1
            or type(stage) is not str
            or stage not in _WORKER_OBSERVATION_STAGE_EVENTS
            or type(event) is not str
            or event not in _WORKER_OBSERVATION_STAGE_EVENTS[stage]
        ):
            return False
    elif (
        progress["record_count"] != 0
        or progress.get("last_stage") is not None
        or progress.get("last_event") is not None
    ):
        return False
    for name, maximum in _WORKER_OBSERVATION_COUNT_LIMITS.items():
        count = counts.get(name)
        if count is not None and (type(count) is not int or not 0 <= count <= maximum):
            return False
    if failure["status"] == "verified" and (
        value["supervisor_result_type"] != "expected"
        or value["supervisor_reason"] != "worker_exit_nonzero"
        or value["supervisor_status"] != "BLOCKED"
        or value["lifecycle_type"] != "expected"
        or value["receipt_type"] != "none"
        or lifecycle["assignment_before_resume"] is not True
        or lifecycle["stdin_fully_sent"] is not True
        or lifecycle["stdout_eof"] is not True
        or lifecycle["stderr_eof"] is not True
        or lifecycle["process_exit_observed"] is not True
        or lifecycle["process_exit_code"] not in {"TWO", "OTHER_NONZERO"}
        or lifecycle["job_active_status"] != "ZERO"
        or lifecycle["handles_closed"] is not True
        or lifecycle["timed_out"] is not False
        or lifecycle["forced_kill"] is not False
        or lifecycle["containment"] != "windows_job"
        or lifecycle["status"] != "BLOCKED"
    ):
        return False
    if value["receipt_type"] == "expected":
        rc_fields = (
            "authenticate_return_code_observed",
            "login_return_code_observed",
            "query_return_code_observed",
            "order_insert_requests",
            "order_cancel_requests",
        )
        if any(counts[name] is None for name in rc_fields):
            return False
        if any(
            counts[zero_name] is not None
            and counts[zero_name] > counts[observed_name]
            for zero_name, observed_name in (
                ("authenticate_return_code_zero", "authenticate_return_code_observed"),
                ("login_return_code_zero", "login_return_code_observed"),
                ("query_return_code_zero", "query_return_code_observed"),
            )
        ) or any(
            (counts[zero_name] is None) != (counts[observed_name] == 0)
            for zero_name, observed_name in (
                ("authenticate_return_code_zero", "authenticate_return_code_observed"),
                ("login_return_code_zero", "login_return_code_observed"),
                ("query_return_code_zero", "query_return_code_observed"),
            )
        ):
            return False
    elif any(
        counts[name] is not None
        for name in (
            "authenticate_return_code_observed",
            "authenticate_return_code_zero",
            "login_return_code_observed",
            "login_return_code_zero",
            "query_return_code_observed",
            "query_return_code_zero",
            "order_insert_requests",
            "order_cancel_requests",
        )
    ):
        return False
    if progress_status != "verified" and any(
        counts[name] is not None
        for name in (
            "authenticate_attempts",
            "authenticate_callback_first",
            "authenticate_callback_terminal",
            "login_attempts",
            "login_callback_first",
            "login_callback_terminal",
            "query_attempts",
            "query_callback_first",
            "query_callback_terminal",
        )
    ):
        return False
    if value["supervisor_result_type"] == "unobserved":
        if not (
            value["supervisor_reason"] == "UNOBSERVED"
            and value["supervisor_status"] == "UNOBSERVED"
            and value["lifecycle_type"] == "unobserved"
            and value["receipt_type"] == "unobserved"
            and progress_status == "UNOBSERVED"
        ):
            return False
    if value["lifecycle_type"] == "unobserved":
        if (
            value["receipt_type"] != "unobserved"
            or progress_status != "UNOBSERVED"
            or any(
                lifecycle.get(name) is not None
                for name in (
                    "assignment_before_resume", "stdin_fully_sent", "stdout_eof", "stderr_eof",
                    "process_exit_observed", "handles_closed", "timed_out", "forced_kill"
                )
            )
            or lifecycle.get("process_exit_code") != "UNOBSERVED"
            or lifecycle.get("job_active_status") != "UNOBSERVED"
            or lifecycle.get("containment") != "UNOBSERVED"
            or lifecycle.get("status") != "UNOBSERVED"
            or any(counts.get(name) is not None for name in _WORKER_OBSERVATION_COUNT_LIMITS)
            or failure["status"] != "UNOBSERVED"
        ):
            return False
    return True


def _valid_post_worker_failure(value: object) -> bool:
    if type(value) is not dict or not {
        "post_worker_failure_stage",
        "post_worker_failure_code",
        "certification",
        "reason",
    }.issubset(value):
        return False
    stage = value["post_worker_failure_stage"]
    code = value["post_worker_failure_code"]
    status = value["certification"]
    reason = value["reason"]
    if (
        type(stage) is not str
        or stage not in _POST_WORKER_FAILURE_STAGES
        or type(code) is not str
        or code not in _POST_WORKER_FAILURE_CODES
        or ((stage == "none") != (code == "none"))
        or (
            stage == "verify_tree"
            and code
            not in (_OWNER_VERIFY_TREE_FAILURE_CODES | {"unclassified_owner_error"})
        )
        or (
            stage == "read_snapshot_artifacts"
            and code
            not in (_OWNER_SNAPSHOT_READ_FAILURE_CODES | {"unclassified_owner_error"})
        )
        or (
            stage != "none"
            and (status != "BLOCKED" or reason != "candidate_owner_validation_failed")
        )
        or (reason == "candidate_owner_validation_failed" and stage == "none")
    ):
        return False
    return True


def _validate_root_child_frame(raw: bytes, *, exit_code: int) -> dict[str, object]:
    if type(raw) is not bytes or len(raw) > _MAX_CLI_FRAME_BYTES or exit_code not in (0, 2):
        raise RootActivationError("cli_result_frame_invalid")
    if raw.endswith(b"\r\n"):
        body = raw[:-2]
    elif raw.endswith(b"\n"):
        body = raw[:-1]
    else:
        raise RootActivationError("cli_result_frame_invalid")
    if not body or b"\r" in body or b"\n" in body:
        raise RootActivationError("cli_result_frame_invalid")
    value = _parse_json(body, _MAX_CLI_FRAME_BYTES)
    if type(value) is not dict or _canonical_json_value(value) != body:
        raise RootActivationError("cli_result_binding_invalid")
    if set(value) == _RESULT_KEYS:
        if (
            exit_code != 2
            or value.get("case_id") != CASE_ID
            or value.get("certification") != "BLOCKED"
            or value.get("mode") != PROFILE_ID
            or value.get("profile") != PROFILE_ID
            or value.get("write_policy") != "NO_WRITE"
            or type(value.get("writes")) is not int
            or value.get("writes") != 0
            or type(value.get("reason")) is not str
            or not _SAFE_REASON.fullmatch(value["reason"])
        ):
            raise RootActivationError("cli_blocked_result_invalid")
        return value
    if (
        set(value) != _ROOT_CHILD_STORED_KEYS
        or exit_code != 0
        or value.get("case_id") != CASE_ID
        or value.get("receipt_type") != _ROOT_CASE_RECEIPT_TYPE
        or value.get("receipt_stored") is not True
        or value.get("write_policy") != "NO_WRITE"
        or type(value.get("writes")) is not int
        or value.get("writes") != 0
    ):
        raise RootActivationError("root_child_result_invalid")
    return value


def _validate_root_case_receipt(raw: bytes) -> dict[str, object]:
    if type(raw) is not bytes or len(raw) > _MAX_ROOT_CASE_RECEIPT_BYTES:
        raise RootActivationError("root_case_receipt_size_invalid")
    if raw.endswith(b"\r\n"):
        body = raw[:-2]
    elif raw.endswith(b"\n"):
        body = raw[:-1]
    else:
        raise RootActivationError("root_case_receipt_frame_invalid")
    if not body or b"\r" in body or b"\n" in body:
        raise RootActivationError("root_case_receipt_frame_invalid")
    value = _parse_json(body, _MAX_ROOT_CASE_RECEIPT_BYTES)
    if type(value) is not dict or _canonical_json_value(value) != body:
        raise RootActivationError("root_case_receipt_binding_invalid")
    if set(value) != _ROOT_CASE_RESULT_KEYS:
        raise RootActivationError("root_case_result_schema_invalid")
    string_fields = (
        "case_id",
        "case_name",
        "scenario_id",
        "scenario_name",
        "category",
        "trace_id",
        "started_at",
        "finished_at",
        "simnow_env",
        "failure_reason",
        "next_action",
    )
    if (
        value.get("case_id") != CASE_ID
        or value.get("status") != "PASS"
        or value.get("scenario_id") != "AUTH-01"
        or value.get("simnow_env") != "simulation"
        or any(type(value.get(key)) is not str for key in string_fields)
        or type(value.get("duration_seconds")) not in (int, float)
        or value["duration_seconds"] < 0
        or type(value.get("optional")) is not bool
        or type(value.get("required_events_present")) is not bool
        or value["required_events_present"] is not True
        or type(value.get("evidence_fields_present")) is not bool
        or value["evidence_fields_present"] is not True
        or any(
            type(value.get(key)) is not list
            or any(type(item) is not str for item in value[key])
            for key in ("required_events", "evidence_fields", "pass_conditions", "observed_events")
        )
        or value["observed_events"] != value["required_events"]
        or value.get("missing_required_events") != []
        or value.get("missing_evidence_fields") != []
        or value.get("evidence") != []
        or value.get("failure_reason") != ""
        or value.get("next_action") != ""
    ):
        raise RootActivationError("root_case_result_binding_invalid")
    details = value.get("details")
    evidence = details.get("certification_evidence") if type(details) is dict else None
    admission = details.get("root_admission") if type(details) is dict else None
    if (
        type(details) is not dict
        or set(details) != {"certification_evidence", "root_admission"}
        or type(evidence) is not dict
        or set(evidence) != {"front_id", "session_id", "trading_day"}
        or type(evidence.get("front_id")) is not int
        or evidence.get("front_id") <= 0
        or type(evidence.get("session_id")) is not str
        or not evidence.get("session_id")
        or type(evidence.get("trading_day")) is not str
        or not evidence.get("trading_day")
        or type(admission) is not dict
        or set(admission)
        != {
            "receipt_type",
            "request_count",
            "query_callback_count",
            "snapshot_count",
            "write_invocation_count",
            "biz_type_state",
        }
        or admission.get("receipt_type") != "C01RootPhysicalPostverifyProof"
        or type(admission.get("request_count")) is not int
        or admission.get("request_count") != 8
        or type(admission.get("query_callback_count")) is not int
        or not 6 <= admission.get("query_callback_count") <= 8
        or type(admission.get("snapshot_count")) is not int
        or admission.get("snapshot_count") != 2
        or type(admission.get("write_invocation_count")) is not int
        or admission.get("write_invocation_count") != 0
        or admission.get("biz_type_state") not in {"unclassified", "unknown_nul_only", "observed"}
    ):
        raise RootActivationError("root_case_result_evidence_invalid")
    audit = value.get("audit_events")
    if (
        type(audit) is not list
        or len(audit) != 1
        or type(audit[0]) is not dict
        or audit[0].get("event_type") != "certification_case_result"
        or audit[0].get("case_id") != CASE_ID
        or audit[0].get("status") != "PASS"
        or audit[0].get("missing_required_events") != []
        or audit[0].get("missing_evidence_fields") != []
    ):
        raise RootActivationError("root_case_result_audit_invalid")
    # Never return the receipt payload or any front/session/day values to the
    # public output path. The only returned values are allowlisted counts.
    return {
        "request_count": 8,
        "query_callback_count": admission["query_callback_count"],
        "snapshot_count": 2,
        "write_invocation_count": 0,
    }


def _store_private_root_case_receipt(
    *,
    root: Path,
    admission_id: str,
    payload: bytes,
    private_module: ModuleType,
    cli_module: ModuleType,
) -> None:
    if (
        type(admission_id) is not str
        or not _ADMISSION_ID.fullmatch(admission_id)
        or type(payload) is not bytes
        or not 0 < len(payload) <= _MAX_ROOT_CASE_RECEIPT_BYTES
        or type(private_module) is not ModuleType
        or private_module.__name__ != "_c01_v18_root_receipt_private_writer"
        or type(cli_module) is not ModuleType
        or cli_module.__name__ != "_c01_v18_root_receipt_cli_writer"
    ):
        raise RootActivationError("root_private_receipt_binding_invalid")
    expected_private = root / Path("backtrader_runtime/certification_roundtrip_private.py")
    expected_cli = root / Path("backtrader_runtime/certification_binance_roundtrip_r3_cli.py")
    if (
        Path(private_module.__file__).resolve(strict=True) != expected_private.resolve(strict=True)
        or Path(cli_module.__file__).resolve(strict=True) != expected_cli.resolve(strict=True)
        or getattr(private_module, "__c01_source_sha256__", None) != _PRIVATE_HELPER_SHA256
        or getattr(cli_module, "__c01_source_sha256__", None) != _R3_CLI_HELPER_SHA256
    ):
        raise RootActivationError("root_private_receipt_source_invalid")
    try:
        local_app_data = Path(cli_module._known_local_app_data()).resolve(strict=True)
        target = private_module._path(
            local_app_data
            / _ADMISSION_ROOT_NAME
            / _ADMISSION_COLLECTION_NAME
            / admission_id
        )
        if not target.is_dir() or target.is_symlink():
            raise ValueError
        children = tuple(target.iterdir())
        if len(children) > 3 or {item.name for item in children} != {"admission.json", "consumed"}:
            raise ValueError
        api = private_module._api()
        sid = api.current_sid()
        with private_module._ancestors(target):
            with api.opened(target, directory=True) as handle:
                api.verify_acl(handle, sid, directory=True)
                device, inode = api.info(handle, directory=True)
        directory = private_module.PrivateArtifactDirectory(target, device, inode)
        digest = directory.write_bytes(_ROOT_CASE_RECEIPT_NAME, payload)
        directory.verify()
    except RootActivationError:
        raise
    except Exception:
        raise RootActivationError("root_private_receipt_store_failed") from None
    if digest != _sha256(payload):
        raise RootActivationError("root_private_receipt_store_mismatch")


def _valid_lifecycle(value: object) -> bool:
    required = {
        "assignment_before_resume",
        "job_active_zero",
        "normal_exit_code",
        "stdout_eof",
        "stderr_eof",
        "stderr_empty",
        "handles_closed",
        "reader_threads_joined",
        "forced_termination",
    }
    if type(value) is not dict or set(value) != required:
        return False
    return (
        value["assignment_before_resume"] is True
        and value["job_active_zero"] is True
        and type(value["normal_exit_code"]) is int
        and value["normal_exit_code"] in (0, 2)
        and value["stdout_eof"] is True
        and value["stderr_eof"] is True
        and value["stderr_empty"] is True
        and value["handles_closed"] is True
        and value["reader_threads_joined"] is True
        and value["forced_termination"] is False
    )


def _valid_root_public_result(value: object) -> bool:
    if type(value) is not dict or set(value) != _ROOT_PUBLIC_RESULT_KEYS:
        return False
    return (
        value.get("case_id") == CASE_ID
        and value.get("certification") == "PASS"
        and value.get("mode") == PROFILE_ID
        and value.get("profile") == PROFILE_ID
        and value.get("reason") == "root_case_receipt_verified"
        and value.get("write_policy") == "NO_WRITE"
        and type(value.get("writes")) is int
        and value.get("writes") == 0
        and value.get("receipt_type") == _ROOT_CASE_RECEIPT_TYPE
        and all(
            type(value.get(name)) is bool and value[name] is True
            for name in (
                "receipt_verified",
                "source_closure_verified",
                "root_postverify_verified",
                "outer_job_empty",
                "stdout_eof",
                "stderr_eof",
                "stderr_empty",
                "job_handles_closed",
                "reader_threads_joined",
                "cleanup_verified",
            )
        )
        and type(value.get("request_count")) is int
        and value.get("request_count") == 8
        and type(value.get("query_callback_count")) is int
        and 6 <= value.get("query_callback_count") <= 8
        and type(value.get("snapshot_count")) is int
        and value.get("snapshot_count") == 2
        and type(value.get("write_invocation_count")) is int
        and value.get("write_invocation_count") == 0
    )


def _capture_thread(capture: _PipeCapture) -> None:
    try:
        while True:
            chunk = capture.stream.read(64 * 1024)
            if not chunk:
                capture.eof = True
                return
            with capture.data_lock:
                if len(capture.data) + len(chunk) > capture.maximum:
                    capture.overflow = True
                elif not capture.overflow:
                    capture.data.extend(chunk)
    except Exception:
        capture.failed = True
    finally:
        try:
            capture.stream.close()
            capture.closed = True
        except Exception:
            capture.failed = True


def _open_child_streams():
    """Create non-inheritable parent pipes and the exact three child handles."""

    import msvcrt

    owned_fds: list[int] = []
    owned_streams: list[Any] = []
    try:
        def make_pipe() -> tuple[int, int]:
            pair = os.pipe()
            owned_fds.extend(pair)
            return pair

        stdin_read, stdin_write = make_pipe()
        stdout_read, stdout_write = make_pipe()
        stderr_read, stderr_write = make_pipe()
        child_fds = (stdin_read, stdout_write, stderr_write)
        for fd in (stdin_write, stdout_read, stderr_read, *child_fds):
            os.set_inheritable(fd, False)
        for fd in child_fds:
            os.set_inheritable(fd, True)
        handles = tuple(int(msvcrt.get_osfhandle(fd)) for fd in child_fds)
        stdout_stream = os.fdopen(stdout_read, "rb", buffering=0)
        owned_fds.remove(stdout_read)
        owned_streams.append(stdout_stream)
        stderr_stream = os.fdopen(stderr_read, "rb", buffering=0)
        owned_fds.remove(stderr_read)
        owned_streams.append(stderr_stream)
        os.close(stdin_write)
        owned_fds.remove(stdin_write)
        return handles, child_fds, (stdout_stream, stderr_stream)
    except Exception:
        for stream in reversed(owned_streams):
            try:
                stream.close()
            except Exception:
                pass
        for fd in reversed(owned_fds):
            try:
                os.close(fd)
            except Exception:
                pass
        raise RootActivationError("cli_pipe_setup_failed") from None


def _wait_job(session: Any, deadline: float, captures: tuple[_PipeCapture, _PipeCapture]):
    exit_code = None
    empty = None
    exit_seen = None
    cleanup_deadline = None
    while True:
        now = time.monotonic()
        active_deadline = deadline if cleanup_deadline is None else cleanup_deadline
        if now >= active_deadline:
            raise RootActivationError("cli_job_drain_incomplete" if exit_seen is not None else "cli_deadline_exceeded")
        if any(item.overflow for item in captures):
            raise RootActivationError("cli_output_limit_exceeded")
        exit_code = session.poll_launcher_exit_code()
        empty = session.poll_job_empty()
        now = time.monotonic()
        if exit_code is not None:
            if exit_seen is None:
                if now >= deadline:
                    raise RootActivationError("cli_deadline_exceeded")
                exit_seen = now
                cleanup_deadline = min(deadline + MAX_CLEANUP_SECONDS, now + MAX_CLEANUP_SECONDS)
            if now >= cleanup_deadline:
                raise RootActivationError("cli_job_drain_incomplete")
            if empty is True:
                return exit_code, cleanup_deadline
        elif now >= deadline:
            raise RootActivationError("cli_deadline_exceeded")
        time.sleep(min(0.025, max(0.0, active_deadline - now)))


def _run_v18_job(
    *,
    backend_module: ModuleType,
    command: SimpleNamespace,
    deadline: float,
    open_streams: Any = _open_child_streams,
    process_id: Any = None,
) -> tuple[bytes, dict[str, object], dict[str, object]]:
    """Run the fixed same-process Root child in a kill-on-close Job."""

    child_fds: list[int] = []
    captures: Optional[tuple[_PipeCapture, _PipeCapture]] = None
    session = None
    backend = None
    released = False
    try:
        child_handles, opened_child_fds, streams = open_streams()
        child_fds = list(opened_child_fds)
        captures = (_PipeCapture(streams[0]), _PipeCapture(streams[1]))
        backend = backend_module.WindowsJobBackend(
            inherited_stdin_handle=child_handles[0],
            inherited_stdout_handle=child_handles[1],
            inherited_stderr_handle=child_handles[2],
        )
        session = backend.create_suspended_in_job(command, deadline_monotonic=deadline)
        for fd in tuple(child_fds):
            os.close(fd)
            child_fds.remove(fd)
        if session.job_assignment_observed is not True or time.monotonic() >= deadline:
            raise RootActivationError("job_assignment_or_deadline_invalid")
        observed_pid = process_id(session) if process_id is not None else _windows_process_id(session)
        if type(observed_pid) is not int or observed_pid <= 0:
            raise RootActivationError("job_process_identity_unavailable")
        for capture in captures:
            capture.thread = threading.Thread(
                target=_capture_thread, args=(capture,), name="c01-v18-root-capture", daemon=True
            )
            capture.thread.start()
        if time.monotonic() >= deadline or not session.resume_launcher():
            raise RootActivationError("job_resume_failed")
        exit_code, cleanup_deadline = _wait_job(session, deadline, captures)
        for capture in captures:
            if capture.thread is not None:
                capture.thread.join(max(0.0, cleanup_deadline - time.monotonic()))
        if any(
            capture.thread is None
            or capture.thread.is_alive()
            or not capture.eof
            or capture.failed
            or capture.overflow
            or not capture.closed
            for capture in captures
        ):
            raise RootActivationError("cli_pipe_drain_incomplete")
        if captures[1].data:
            raise RootActivationError("cli_stderr_not_empty")
        raw_result = bytes(captures[0].data)
        result = _validate_root_child_frame(raw_result, exit_code=exit_code)
        if not session.release_controls():
            raise RootActivationError("cli_job_handles_not_closed")
        released = True
        lifecycle = {
            "assignment_before_resume": True,
            "job_active_zero": True,
            "normal_exit_code": exit_code,
            "stdout_eof": captures[0].eof,
            "stderr_eof": captures[1].eof,
            "stderr_empty": not captures[1].data,
            "handles_closed": released,
            "reader_threads_joined": all(not item.thread.is_alive() for item in captures),
            "forced_termination": False,
        }
        if not _valid_lifecycle(lifecycle):
            raise RootActivationError("cli_lifecycle_unconfirmed")
        return raw_result, result, lifecycle
    except RootActivationError:
        raise
    except Exception:
        raise RootActivationError("outer_job_failed") from None
    finally:
        fd_cleanup_confirmed = True
        for fd in tuple(child_fds):
            try:
                os.close(fd)
            except Exception:
                fd_cleanup_confirmed = False
            else:
                child_fds.remove(fd)
        if captures is not None:
            for capture in captures:
                if capture.thread is None or capture.thread.ident is None:
                    try:
                        capture.stream.close()
                    except Exception:
                        pass
        if session is not None and not released:
            cleanup_confirmed = fd_cleanup_confirmed
            try:
                session.terminate_job()
            except Exception:
                cleanup_confirmed = False
            cleanup_deadline = time.monotonic() + MAX_CLEANUP_SECONDS
            exit_observed = None
            empty_observed = None
            while time.monotonic() < cleanup_deadline:
                try:
                    exit_observed = session.poll_launcher_exit_code()
                    empty_observed = session.poll_job_empty()
                    if exit_observed is not None and empty_observed is True:
                        break
                except Exception:
                    break
                time.sleep(0.025)
            if captures is not None:
                for capture in captures:
                    if capture.thread is not None and capture.thread.ident is not None:
                        capture.thread.join(max(0.0, cleanup_deadline - time.monotonic()))
            readers_stopped = captures is None or all(
                capture.thread is None or not capture.thread.is_alive() for capture in captures
            )
            streams_closed = captures is None or all(
                capture.closed or getattr(capture.stream, "closed", False) for capture in captures
            )
            controls_released = False
            if exit_observed is not None and empty_observed is True:
                try:
                    controls_released = session.release_controls() is True
                except Exception:
                    controls_released = False
            cleanup_confirmed = (
                cleanup_confirmed
                and exit_observed is not None
                and empty_observed is True
                and readers_stopped
                and streams_closed
                and controls_released
            )
            if not cleanup_confirmed:
                _ROOT_RETAINED_UNRESOLVED_JOB_REFS.append(
                    (session, backend, captures, tuple(child_fds))
                )
                raise RootActivationError("cli_cleanup_unconfirmed")


def _windows_process_id(session: Any) -> int:
    import ctypes
    from ctypes import wintypes

    handle = getattr(session, "_process_handle", None)
    if type(handle) is not int or handle <= 0 or os.name != "nt":
        raise RootActivationError("job_process_handle_unavailable")
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    get_pid = kernel32.GetProcessId
    get_pid.argtypes = [wintypes.HANDLE]
    get_pid.restype = wintypes.DWORD
    pid = int(get_pid(handle))
    if pid <= 0:
        raise RootActivationError("job_process_identity_unavailable")
    return pid


def _run_core(ports: Any, *, wrapper_sha256: str, clock: Any = time.monotonic) -> _ActivationOutput:
    """Fakeable orchestration; production CLI supplies only fixed Root ports."""

    lifecycle = None
    try:
        source_policy = _validate_source_policy(ports.source_policy())
        if source_policy["profile_id"] != PROFILE_ID:
            raise RootActivationError("v18_source_policy_mismatch")
        ports.verify_runtime_binding()
        ports.require_clean_ambient_names()
        with ports.activation_namespace_lease():
            with ports.config_lease() as (front_pairs, config_digest, verify_config):
                if type(front_pairs) not in (tuple, list) or not 1 <= len(front_pairs) <= 8:
                    raise RootActivationError("configured_front_pair_count_invalid")
                if type(config_digest) is not str or not _SHA256.fullmatch(config_digest):
                    raise RootActivationError("config_digest_invalid")
                selection_deadline = clock() + _MAX_PAIR_SELECTION_SECONDS
                binding = ports.select_current_pair(front_pairs, deadline=selection_deadline)
                if clock() >= selection_deadline:
                    raise RootActivationError("pair_selection_deadline_exceeded")
                projection = ports.pair_projection(front_pairs)
                projection_sha256 = _sha256(projection)
                selected_pair = ports.selected_pair_from_binding(
                    front_pairs, binding, projection_sha256=projection_sha256
                )
                index = getattr(binding, "selected_index", None)
                if (
                    type(index) is not int
                    or not 0 <= index < len(front_pairs)
                    or selected_pair != front_pairs[index]
                ):
                    raise RootActivationError("selected_pair_binding_invalid")
                verify_config()
                # The CREATE_NEW Root marker is placed after complete-pair
                # selection but before the first protected .env read.
                ports.claim_root_activation(wrapper_sha256)
                with ports.credential_lease(front_pairs, binding, projection_sha256) as credentials:
                    account_digest, credential_digest = ports.credential_digests(credentials)
                    if (
                        type(account_digest) is not str
                        or not _SHA256.fullmatch(account_digest)
                        or type(credential_digest) is not str
                        or not _SHA256.fullmatch(credential_digest)
                    ):
                        raise RootActivationError("credential_binding_invalid")
                    verify_config()
                    admission_id = ports.new_admission_id()
                    required_bindings = ports.required_bindings(source_policy)
                    raw_admission = _build_admission_document(
                        admission_id=admission_id,
                        required_bindings=required_bindings,
                        configured_pair_count=len(front_pairs),
                        config_sha256=config_digest,
                        account_scope_sha256=account_digest,
                        credential_binding_sha256=credential_digest,
                        now=ports.now_utc(),
                    )
                    ports.write_admission(admission_id, raw_admission, wrapper_sha256)
        deadline = clock() + MAX_CLI_SECONDS
        result, lifecycle = ports.run_fixed_cli(
            deadline=deadline, cleanup_seconds=MAX_CLEANUP_SECONDS
        )
        if not _valid_lifecycle(lifecycle):
            raise RootActivationError("cli_lifecycle_unconfirmed")
        if _valid_root_public_result(result) and lifecycle.get("normal_exit_code") == 0:
            return _ActivationOutput(value=result, exit_code=0)
        if (
            type(result) is dict
            and result.get("certification") == "BLOCKED"
            and type(result.get("reason")) is str
            and _SAFE_REASON.fullmatch(result["reason"])
            and lifecycle.get("normal_exit_code") == 2
        ):
            return _ActivationOutput(
                value=_public_blocked(result["reason"], lifecycle), exit_code=2
            )
        raise RootActivationError("cli_result_lifecycle_mismatch")
    except RootActivationError as error:
        return _ActivationOutput(value=_public_blocked(error.reason, lifecycle), exit_code=2)
    except Exception:
        # Provider values, filesystem exceptions and private parser messages
        # must never be copied into the public stdout result.
        return _ActivationOutput(
            value=_public_blocked("root_activation_blocked", lifecycle), exit_code=2
        )


class _ProductionPorts:
    """Current V18 source-backed protected reader and fixed Job command."""

    def __init__(
        self,
        root: Path,
        bundle: Any,
        runner_source: bytes,
        *,
        wrapper_sha256: str,
        entry_sha256: str,
    ):
        self.root = root
        self.bundle = bundle
        self.issuer = bundle.issuer
        self.owner = bundle.owner
        self.helpers = dict(bundle.helpers)
        self.runner_source = runner_source
        self.wrapper_sha256 = wrapper_sha256
        self.entry_sha256 = entry_sha256
        self._api = None
        self._user_profile: Optional[Path] = None
        self._namespace_stack = None
        self._namespace_root: Optional[Path] = None
        self._namespace_collection: Optional[Path] = None
        self._root_claimed = False
        self._admission_id: Optional[str] = None
        self._admission_directory: Any = None
        self._admission_collection_path: Optional[Path] = None

    def source_policy(self) -> dict[str, str]:
        return dict(_EXPECTED_SOURCE_POLICY)

    def verify_runtime_binding(self) -> None:
        verifier = self.helpers["interpreter_binding"].verify_current_runtime
        if verifier() is not True:
            raise RootActivationError("approved_cpython311_consumer_required")

    def require_clean_ambient_names(self) -> None:
        self.issuer._require_clean_ambient_secrets()

    def config_lease(self):
        return self.issuer._private_pair_config_lease(self.root, self.helpers)

    @contextmanager
    def activation_namespace_lease(self):
        from contextlib import ExitStack

        private = self.helpers["private"]
        root_dir, collection_dir, _profile, api, sid = self._protected_paths()
        self._admission_id = None
        self._admission_directory = None
        self._admission_collection_path = None
        try:
            with ExitStack() as retained:
                self._ensure_private_directory(root_dir, api=api, sid=sid, retained=retained)
                self._ensure_private_directory(collection_dir, api=api, sid=sid, retained=retained)
                retained.enter_context(
                    self.issuer._admission_directory_ancestor_locks(
                        collection_dir, private, api
                    )
                )
                root_handle = retained.enter_context(
                    self.issuer._open_admission_directory(api, root_dir)
                )
                api.verify_acl(root_handle, sid, directory=True)
                collection_handle = retained.enter_context(
                    self.issuer._open_admission_directory(api, collection_dir)
                )
                api.verify_acl(collection_handle, sid, directory=True)
                if (
                    {item.name for item in root_dir.iterdir()} != {_ADMISSION_COLLECTION_NAME}
                    or tuple(collection_dir.iterdir())
                ):
                    raise RootActivationError("admission_namespace_not_fresh")
                self._namespace_root = root_dir
                self._namespace_collection = collection_dir
                self._namespace_stack = retained
                yield
        except RootActivationError:
            raise
        except Exception:
            raise RootActivationError("admission_namespace_unavailable") from None
        finally:
            self._namespace_stack = None
            self._namespace_root = None
            self._namespace_collection = None
            self._root_claimed = False

    def claim_root_activation(self, wrapper_sha256: str) -> None:
        if self._namespace_stack is None or self._namespace_root is None or self._root_claimed:
            raise RootActivationError("root_activation_claim_state_invalid")
        private = self.helpers["private"]
        r3_cli = self.helpers["r3_cli"]
        api = self._api
        sid = api.current_sid()
        try:
            claim = private.create_private_directory(self._namespace_root / _ROOT_ONESHOT_NAME)
            claim_handle = self._namespace_stack.enter_context(
                self.issuer._open_admission_directory(api, private._path(claim.path))
            )
            api.verify_acl(claim_handle, sid, directory=True)
            raw = _canonical_json(
                {
                    "schema": _ROOT_ONESHOT_SCHEMA,
                    "profile_id": PROFILE_ID,
                    "case_id": CASE_ID,
                    "wrapper_source_sha256": wrapper_sha256,
                }
            )
            claim.write_bytes("claim.json", raw)
            claim_path = private._path(claim.path / "claim.json")
            handle, _identity = self._namespace_stack.enter_context(
                r3_cli._locked_readonly_file(claim_path, private, api)
            )
            api.verify_acl(handle, sid, directory=False)
            if r3_cli._read_bounded_handle(api, handle, 4096) != raw:
                raise RootActivationError("root_activation_claim_invalid")
            self._root_claimed = True
        except RootActivationError:
            raise
        except Exception:
            raise RootActivationError("root_activation_already_used") from None

    def select_current_pair(self, front_pairs: Sequence[Mapping[str, str]], *, deadline: float):
        audit: dict[str, Any] = {}
        try:
            return self.issuer._select_current_pair(
                self.helpers, front_pairs, deadline=deadline, audit_sink=audit
            )
        except Exception as error:
            if type(error) is self.issuer._IssuerError and error.args:
                reason = error.args[0]
                if type(reason) is str and _SAFE_REASON.fullmatch(reason):
                    raise RootActivationError(reason) from None
            raise RootActivationError("pair_selection_failed") from None

    def pair_projection(self, front_pairs: Sequence[Mapping[str, str]]) -> bytes:
        return self.issuer._pair_projection(self.helpers, front_pairs)

    def selected_pair_from_binding(
        self, front_pairs: Sequence[Mapping[str, str]], binding: Any, *, projection_sha256: str
    ) -> dict[str, str]:
        selected = self.issuer._selected_pair_from_binding(
            self.helpers,
            front_pairs,
            binding,
            expected_projection_sha256=projection_sha256,
        )
        if type(selected) is not dict or set(selected) != {"md_front", "td_front"}:
            raise RootActivationError("selected_pair_binding_invalid")
        return selected

    def credential_lease(self, front_pairs: Sequence[Mapping[str, str]], binding: Any, projection: str):
        return self.issuer._credential_lease(
            self.owner,
            self.root,
            self.helpers,
            front_pairs,
            binding,
            expected_projection_sha256=projection,
        )

    def credential_digests(self, credentials: Any) -> tuple[str, str]:
        protocol = self.helpers["protocol"]
        return (
            protocol.compute_account_scope_sha256(credentials.broker_id, credentials.user_id),
            protocol.compute_credential_binding_sha256(
                credentials.broker_id,
                credentials.user_id,
                credentials.password,
                credentials.app_id,
                credentials.auth_code,
                credentials.product_info,
            ),
        )

    def new_admission_id(self) -> str:
        return secrets.token_hex(16)

    def now_utc(self) -> datetime:
        return datetime.now(timezone.utc)

    def required_bindings(self, source_policy: Mapping[str, str]) -> dict[str, str]:
        return self.issuer._required_admission_bindings(
            issuer_source_sha256=source_policy["issuer_source_sha256"],
            case_runner_source_sha256=source_policy["case_runner_source_sha256"],
        )

    def _protected_paths(self) -> tuple[Path, Path, Path, Any, str]:
        private = self.helpers["private"]
        r3_cli = self.helpers["r3_cli"]
        api = private._api()
        sid = api.current_sid()
        local_app_data = Path(r3_cli._known_local_app_data()).resolve(strict=True)
        profile_text = os.environ.get("USERPROFILE")
        if type(profile_text) is not str or not profile_text:
            raise RootActivationError("admission_known_folder_unavailable")
        profile = private._path(Path(profile_text)).resolve(strict=True)
        if (
            not local_app_data.is_absolute()
            or not profile.is_dir()
            or os.path.normcase(str(local_app_data.parents[1])) != os.path.normcase(str(profile))
        ):
            raise RootActivationError("admission_known_folder_mismatch")
        root_dir = private._path(local_app_data / _ADMISSION_ROOT_NAME)
        collection_dir = private._path(root_dir / _ADMISSION_COLLECTION_NAME)
        self._api = api
        self._user_profile = profile
        return root_dir, collection_dir, profile, api, sid

    def _ensure_private_directory(self, path: Path, *, api: Any, sid: str, retained: Any):
        private = self.helpers["private"]
        if os.path.lexists(path):
            directory = api.opened(private._path(path), directory=True)
            handle = retained.enter_context(directory)
            api.verify_acl(handle, sid, directory=True)
            return private.PrivateArtifactDirectory(path, *api.info(handle, directory=True))
        created = private.create_private_directory(path)
        handle = retained.enter_context(api.opened(private._path(path), directory=True))
        api.verify_acl(handle, sid, directory=True)
        if api.info(handle, directory=True) != (created.device, created.inode):
            raise RootActivationError("admission_directory_identity_invalid")
        return created

    def write_admission(self, admission_id: str, payload: bytes, wrapper_sha256: str) -> None:
        if type(payload) is not bytes or not 0 < len(payload) <= _MAX_ADMISSION_BYTES:
            raise RootActivationError("admission_size_invalid")
        if (
            not self._root_claimed
            or self._namespace_stack is None
            or self._namespace_collection is None
        ):
            raise RootActivationError("root_activation_claim_required")
        private = self.helpers["private"]
        r3_cli = self.helpers["r3_cli"]
        api = self._api
        sid = api.current_sid()
        try:
            admission_directory = private.create_private_directory(
                self._namespace_collection / admission_id
            )
            if admission_directory.path.name != admission_id:
                raise RootActivationError("admission_directory_identity_invalid")
            directory_handle = self._namespace_stack.enter_context(
                self.issuer._open_admission_directory(api, private._path(admission_directory.path))
            )
            api.verify_acl(directory_handle, sid, directory=True)
            admission_directory.write_bytes("admission.json", payload)
            admission_path = private._path(admission_directory.path / "admission.json")
            admission_file, _identity = self._namespace_stack.enter_context(
                r3_cli._locked_readonly_file(admission_path, private, api)
            )
            api.verify_acl(admission_file, sid, directory=False)
            if r3_cli._read_bounded_handle(api, admission_file, _MAX_ADMISSION_BYTES) != payload:
                raise RootActivationError("admission_readback_mismatch")
            self.issuer._parse_profile_admission(
                payload,
                expected_bindings=self.required_bindings(_EXPECTED_SOURCE_POLICY),
            )
            self._admission_id = admission_id
            self._admission_directory = admission_directory
            self._admission_collection_path = self._namespace_collection
        except RootActivationError:
            raise
        except Exception:
            raise RootActivationError("admission_write_failed") from None

    def _fixed_command(self) -> SimpleNamespace:
        binding = self.helpers["interpreter_binding"]
        private = self.helpers["private"]
        r3_cli = self.helpers["r3_cli"]
        python = Path(binding.CPYTHON_EXECUTABLE)
        git_path = Path(r3_cli._git_executable(private)).resolve(strict=True)
        systemroot = os.environ.get("SYSTEMROOT", "")
        windir = os.environ.get("WINDIR", "")
        if not systemroot or not windir or self._user_profile is None:
            raise RootActivationError("fixed_windows_environment_unavailable")
        if (
            type(self._admission_id) is not str
            or not _ADMISSION_ID.fullmatch(self._admission_id)
            or self._admission_directory is None
        ):
            raise RootActivationError("root_admission_identity_unavailable")
        runner = self.root / Path(_ENTRY_RELATIVE)
        return SimpleNamespace(
            argv=(
                str(python),
                "-I",
                "-S",
                "-B",
                str(runner),
                "--root-child-v18",
                "--expected-wrapper-sha256",
                self.wrapper_sha256,
                "--expected-entry-sha256",
                self.entry_sha256,
                "--root-case-receipt-admission-id",
                self._admission_id,
            ),
            cwd=str(self.root),
            env={
                "SYSTEMROOT": systemroot,
                "WINDIR": windir,
                "USERPROFILE": str(self._user_profile),
                "PATH": str(git_path.parent),
            },
        )

    def run_fixed_cli(self, *, deadline: float, cleanup_seconds: float):
        if cleanup_seconds != MAX_CLEANUP_SECONDS:
            raise RootActivationError("outer_job_budget_invalid")
        command = self._fixed_command()
        _raw_frame, child_result, lifecycle = _run_v18_job(
            backend_module=self.helpers["job_backend"], command=command, deadline=deadline
        )
        if child_result.get("certification") == "BLOCKED":
            reason = child_result.get("reason")
            return (
                _public_blocked(
                    reason if type(reason) is str else "root_child_blocked", lifecycle
                ),
                lifecycle,
            )
        try:
            if (
                set(child_result) != _ROOT_CHILD_STORED_KEYS
                or child_result.get("receipt_type") != _ROOT_CASE_RECEIPT_TYPE
                or child_result.get("receipt_stored") is not True
                or not _valid_lifecycle(lifecycle)
            ):
                raise RootActivationError("root_child_receipt_marker_invalid")
            private_receipt = self._read_private_root_case_receipt()
            projection = _root_pass_projection(private_receipt["query_callback_count"], lifecycle)
            return projection, lifecycle
        except RootActivationError as error:
            return _public_blocked(error.reason, lifecycle), lifecycle
        except Exception:
            return _public_blocked("root_private_receipt_unavailable", lifecycle), lifecycle

    def _read_private_root_case_receipt(self) -> dict[str, object]:
        directory = self._admission_directory
        admission_id = self._admission_id
        private = self.helpers["private"]
        r3_cli = self.helpers["r3_cli"]
        api = self._api
        if (
            directory is None
            or type(admission_id) is not str
            or not _ADMISSION_ID.fullmatch(admission_id)
            or api is None
            or directory.path.name != admission_id
            or self._admission_collection_path is None
            or directory.path != self._admission_collection_path / admission_id
        ):
            raise RootActivationError("root_private_receipt_binding_invalid")
        receipt_path = private._path(directory.path / _ROOT_CASE_RECEIPT_NAME)
        sid = api.current_sid()
        try:
            with self.issuer._admission_directory_ancestor_locks(receipt_path, private, api):
                directory_handle = self.issuer._open_admission_directory(api, directory.path)
                with directory_handle as handle:
                    if api.info(handle, directory=True) != (directory.device, directory.inode):
                        raise RootActivationError("root_private_receipt_directory_changed")
                    api.verify_acl(handle, sid, directory=True)
                children = tuple(directory.path.iterdir())
                if len(children) > 3 or {item.name for item in children} != {
                    "admission.json",
                    "consumed",
                    _ROOT_CASE_RECEIPT_NAME,
                }:
                    raise RootActivationError("root_private_receipt_namespace_invalid")
                consumed = directory.path / "consumed"
                consumed_handle = self.issuer._open_admission_directory(api, consumed)
                with consumed_handle as handle:
                    api.verify_acl(handle, sid, directory=True)
                consumed_children = tuple(consumed.iterdir())
                if len(consumed_children) != 1 or consumed_children[0].name != "consumed.json":
                    raise RootActivationError("root_private_receipt_consumption_invalid")
                file_context = r3_cli._locked_readonly_file(receipt_path, private, api)
                with file_context as (handle, identity):
                    api.verify_acl(handle, sid, directory=False)
                    if type(identity) is not tuple or len(identity) != 2:
                        raise RootActivationError("root_private_receipt_identity_invalid")
                    raw = r3_cli._read_bounded_handle(api, handle, _MAX_ROOT_CASE_RECEIPT_BYTES)
                    result = _validate_root_case_receipt(raw)
                return result
        except RootActivationError:
            raise
        except Exception:
            raise RootActivationError("root_private_receipt_unavailable") from None


def _run_production(wrapper_sha256: str) -> _ActivationOutput:
    try:
        if (
            os.name != "nt"
            or not sys.flags.isolated
            or not sys.flags.no_site
            or not sys.dont_write_bytecode
            or tuple(sys.version_info[:3]) != (3, 11, 5)
            or struct.calcsize("P") * 8 != 64
        ):
            raise RootActivationError("fixed_runtime_required")
        root = REPO_ROOT
        expected_entry = root / Path(_ENTRY_RELATIVE)
        if Path(__file__).resolve(strict=True) != expected_entry.resolve(strict=True):
            raise RootActivationError("root_source_path_mismatch")
        own = _read_own_source()
        if _sha256(own) != wrapper_sha256:
            raise RootActivationError("root_source_changed")
        with _verified_v18_sources(root) as (
            bundle,
            policy,
            runner_source,
            _entry_raw,
            _public_pins,
            _software_pins,
            _complete_pins,
        ):
            ports = _ProductionPorts(
                root,
                bundle,
                runner_source,
                wrapper_sha256=wrapper_sha256,
                entry_sha256=_ROOT_ENTRY_SHA256,
            )
            return _run_core(ports, wrapper_sha256=wrapper_sha256)
    except RootActivationError as error:
        return _ActivationOutput(value=_public_blocked(error.reason), exit_code=2)
    except Exception:
        return _ActivationOutput(value=_public_blocked("root_activation_blocked"), exit_code=2)


def main(argv: Optional[Sequence[str]] = None) -> int:
    """Default-closed public CLI; fake ports are never accepted here."""

    is_child = False
    try:
        own_source = _read_own_source()
        arguments = list(sys.argv[1:] if argv is None else argv)
        is_child = bool(arguments and arguments[0] == "--root-child-v18")
        if arguments and arguments[0] == "--root-child-v18":
            wrapper_sha256, entry_sha256, admission_id = _parse_root_child_args(
                arguments, own_source
            )
            return _write_output(
                _run_root_entry_child(
                    wrapper_sha256=wrapper_sha256,
                    entry_sha256=entry_sha256,
                    admission_id=admission_id,
                )
            )
        expected = _parse_activation_args(arguments, own_source)
        return _write_output(_run_production(expected))
    except RootActivationError as error:
        return _write_output(
            _ActivationOutput(
                value=_blocked(error.reason) if is_child else _public_blocked(error.reason),
                exit_code=2,
            )
        )
    except Exception:
        return _write_output(
            _ActivationOutput(
                value=_blocked("root_activation_blocked")
                if is_child
                else _public_blocked("root_activation_blocked"),
                exit_code=2,
            )
        )


if __name__ == "__main__":
    raise SystemExit(main())

