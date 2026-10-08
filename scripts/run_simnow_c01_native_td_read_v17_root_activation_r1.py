"""One-shot Root activation for the frozen SimNow C01 V17 TD-read profile.

This source-only candidate is deliberately unregistered. The public entry
requires both an exact self SHA-256 and a confirmation flag. Its V17 admission
is created only after the current protected config has been parsed, complete
pair selection has finished, and the exact selected pair has been bound to a
bounded protected credential read. The child is the fixed V17 case runner in a
Windows Job; only its exact V17 result, after clean capture and Job teardown,
can become a Root result.

Importing this module is inert. Fake tests inject ports into the private core;
the CLI always constructs the fixed production ports below. No V3 or V17 source
globals are patched.
"""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass, field as dataclass_field
from datetime import datetime, timedelta, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import secrets
import struct
import sys
import threading
import time
from types import MappingProxyType, ModuleType, SimpleNamespace
from typing import Any, Mapping, Optional, Sequence


PROFILE_ID = "C01_NATIVE_TD_READ_V17"
CASE_ID = "C01"
REPO_ROOT = Path("D:/source_code/backtrader")
_ENTRY_RELATIVE = "scripts/run_simnow_c01_native_td_read_v17_root_activation_r1.py"
_V17_RELATIVE = "backtrader_runtime/certification_simnow_c01_native_td_read_v17.py"
_V17_SHA256 = "fa202e00da45fced059b6409e17c2ea9d41b0f8e0f1666f56491735a7f39b795"
_V17_MANIFEST_RELATIVE = "backtrader_runtime/certification_simnow_c01_native_td_read_v17.sources.json"
_V17_MANIFEST_SHA256 = "67e395d89835daccbd9e33a5c5f815c192ffc7a4eef1b2d0963de5ae477ff36c"
_V17_SCHEMA_RELATIVE = "backtrader_runtime/certification_simnow_c01_native_td_read_v17.admission.schema.json"
_V17_SCHEMA_SHA256 = "78e497a308fccd928bf9562f83714baf8b2fcbcf406f6e2571407c682d01af6a"
_CASE_RUNNER_RELATIVE = "examples/000_live_certification/simnow_penetration/cases/C01/run_v17.py"
_CASE_RUNNER_SHA256 = "9d34964cae9eb4b6a7435cb77a641dab6fb4c08a38eb4ac4e357a81c007cbd9d"
_FRONT_TRANSPORT_RELATIVE = "backtrader_runtime/certification_simnow_c01_front_transport_v11.py"
_FRONT_TRANSPORT_SHA256 = "3709567730c90e9e9c3168c439f291988a0561497edcd2f8c46822482dda5bc3"
_FRONT_MODULE_NAME = "backtrader_runtime._c01_v17_root_front_transport_v11_source"
_ADMISSION_SCHEMA = "simnow.c01.native_td_read_v17.admission.v1"
_ADMISSION_ROOT_NAME = "simnow-c01-native-td-read-v17"
_ADMISSION_COLLECTION_NAME = "admissions"
_ROOT_ONESHOT_NAME = "root-activation-claimed"
_ROOT_ONESHOT_SCHEMA = "simnow.c01.native_td_read_v17.root_activation_claim.v1"
_MAX_SOURCE_BYTES = 2 * 1024 * 1024
_MAX_SMALL_BYTES = 256 * 1024
_MAX_ADMISSION_BYTES = 16 * 1024
_MAX_CLI_FRAME_BYTES = 64 * 1024
_MAX_CLI_OUTPUT_BYTES = 8 * 1024 * 1024
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
    "issuer_source_sha256": _V17_SHA256,
    "source_manifest_sha256": _V17_MANIFEST_SHA256,
    "admission_schema_sha256": _V17_SCHEMA_SHA256,
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
    """A redacted fixed-category failure from the V17 Root entry."""

    def __init__(self, reason: str):
        if type(reason) is not str or not _SAFE_REASON.fullmatch(reason):
            reason = "root_activation_blocked"
        self.reason = reason
        super().__init__(reason)


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


def _emit(result: Mapping[str, object]) -> int:
    print(_canonical_json_value(dict(result)).decode("ascii"))
    return 0 if result.get("certification") == "PASS" else 2


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
    if argv[0] != "--activate-c01-v17-td-read" or argv[1] != "--expected-wrapper-sha256":
        raise RootActivationError("root_confirmation_required")
    expected = argv[2]
    if type(expected) is not str or not _SHA256.fullmatch(expected):
        raise RootActivationError("root_source_pin_invalid")
    if _sha256(own_source) != expected:
        raise RootActivationError("root_source_pin_mismatch")
    return expected


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


@contextmanager
def _verified_v17_sources(root: Path):
    """Open the independently reviewed V17/front transport public closure."""

    if not isinstance(root, Path) or root.resolve(strict=True) != REPO_ROOT.resolve(strict=True):
        raise RootActivationError("repository_root_mismatch")
    front_raw = _read_pinned_public_file(
        root, _FRONT_TRANSPORT_RELATIVE, _FRONT_TRANSPORT_SHA256, _MAX_SOURCE_BYTES
    )
    runner_raw = _read_pinned_public_file(
        root, _CASE_RUNNER_RELATIVE, _CASE_RUNNER_SHA256, _MAX_SOURCE_BYTES
    )
    _read_pinned_public_file(root, _V17_MANIFEST_RELATIVE, _V17_MANIFEST_SHA256, _MAX_SMALL_BYTES)
    _read_pinned_public_file(root, _V17_SCHEMA_RELATIVE, _V17_SCHEMA_SHA256, _MAX_SMALL_BYTES)
    module = ModuleType(_FRONT_MODULE_NAME)
    module.__file__ = str(root / Path(_FRONT_TRANSPORT_RELATIVE))
    module.__package__ = "backtrader_runtime"
    if _FRONT_MODULE_NAME in __import__("sys").modules:
        raise RootActivationError("front_source_already_loaded")
    __import__("sys").modules[_FRONT_MODULE_NAME] = module
    bundle_context = None
    try:
        exec(compile(front_raw, module.__file__, "exec", dont_inherit=True), module.__dict__)
        bundle_context = module.verified_c01_v17_sources(root)
        bundle = bundle_context.__enter__()
        source_policy = dict(_EXPECTED_SOURCE_POLICY)
        if (
            type(bundle) is not module.VerifiedC01V17SourceBundle
            or bundle._active is not True
            or bundle.issuer.PROFILE_ID != PROFILE_ID
            or bundle.issuer.__c01_source_sha256__ != _V17_SHA256
            or _sha256(runner_raw) != _CASE_RUNNER_SHA256
        ):
            raise RootActivationError("v17_source_policy_mismatch")
        yield bundle, source_policy, runner_raw
    except RootActivationError:
        raise
    except Exception:
        raise RootActivationError("v17_source_bundle_unavailable") from None
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
        raise RootActivationError("v17_source_policy_mismatch")
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


def _validate_v17_result(raw: bytes, *, exit_code: int) -> dict[str, object]:
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
    if type(value) is not dict or set(value) != _RESULT_KEYS:
        raise RootActivationError("cli_result_schema_invalid")
    if value.get("mode") != PROFILE_ID or value.get("profile") != PROFILE_ID:
        raise RootActivationError("cli_result_profile_mismatch")
    if (
        value.get("case_id") != CASE_ID
        or value.get("certification") not in {"PASS", "BLOCKED"}
        or value.get("write_policy") != "NO_WRITE"
        or type(value.get("writes")) is not int
        or value.get("writes") != 0
        or type(value.get("reason")) is not str
        or not _SAFE_REASON.fullmatch(value["reason"])
        or type(value.get("admission_failure_stage")) is not str
        or value["admission_failure_stage"] not in _ADMISSION_FAILURE_STAGES
        or type(value.get("admission_failure_class")) is not str
        or value["admission_failure_class"] not in _ADMISSION_FAILURE_CLASSES
        or (
            (value["admission_failure_stage"] == "none")
            != (value["admission_failure_class"] == "none")
        )
        or (
            value["certification"] == "PASS"
            and value["admission_failure_stage"] != "none"
        )
        or (
            value["admission_failure_stage"] != "none"
            and (
                value["certification"] != "BLOCKED"
                or value["reason"]
                not in {"admission_lease_failed", "admission_source_handle_close_failed"}
            )
        )
        or (
            value["reason"]
            in {"admission_lease_failed", "admission_source_handle_close_failed"}
            and value["admission_failure_stage"] == "none"
        )
        or not _valid_worker_observation(value.get("worker_observation"))
        or not _valid_post_worker_failure(value)
        or (
            value["reason"] in _WORKER_OBSERVATION_REQUIRED_REASONS
            and value.get("worker_observation") is None
        )
        or (value["certification"] == "PASS" and (exit_code != 0 or value["reason"] != "read_only_candidate_complete"))
        or (value["certification"] == "BLOCKED" and exit_code != 2)
        or _canonical_json_value(value) != body
    ):
        raise RootActivationError("cli_result_binding_invalid")
    return value


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


def _validate_v17_payload(value: object) -> dict[str, object]:
    if type(value) is not dict or set(value) != _RESULT_KEYS:
        raise RootActivationError("cli_result_schema_invalid")
    if (
        value.get("case_id") != CASE_ID
        or value.get("certification") not in {"PASS", "BLOCKED"}
        or value.get("mode") != PROFILE_ID
        or value.get("profile") != PROFILE_ID
        or value.get("write_policy") != "NO_WRITE"
        or type(value.get("writes")) is not int
        or value.get("writes") != 0
        or type(value.get("reason")) is not str
        or not _SAFE_REASON.fullmatch(value["reason"])
        or type(value.get("admission_failure_stage")) is not str
        or value["admission_failure_stage"] not in _ADMISSION_FAILURE_STAGES
        or type(value.get("admission_failure_class")) is not str
        or value["admission_failure_class"] not in _ADMISSION_FAILURE_CLASSES
        or (
            (value["admission_failure_stage"] == "none")
            != (value["admission_failure_class"] == "none")
        )
        or (
            value["certification"] == "PASS"
            and (
                value["reason"] != "read_only_candidate_complete"
                or value["admission_failure_stage"] != "none"
            )
        )
        or (
            value["admission_failure_stage"] != "none"
            and (
                value["certification"] != "BLOCKED"
                or value["reason"]
                not in {"admission_lease_failed", "admission_source_handle_close_failed"}
            )
        )
        or (
            value["reason"]
            in {"admission_lease_failed", "admission_source_handle_close_failed"}
            and value["admission_failure_stage"] == "none"
        )
        or not _valid_worker_observation(value.get("worker_observation"))
        or not _valid_post_worker_failure(value)
        or (
            value["reason"] in _WORKER_OBSERVATION_REQUIRED_REASONS
            and value.get("worker_observation") is None
        )
    ):
        raise RootActivationError("cli_result_profile_mismatch")
    return dict(value)


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


def _run_v17_job(
    *,
    backend_module: ModuleType,
    command: SimpleNamespace,
    deadline: float,
    open_streams: Any = _open_child_streams,
    process_id: Any = None,
) -> tuple[dict[str, object], dict[str, object]]:
    """Run the fixed V17 command in a kill-on-close Job with bounded capture."""

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
                target=_capture_thread, args=(capture,), name="c01-v17-root-capture", daemon=True
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
        result = _validate_v17_result(bytes(captures[0].data), exit_code=exit_code)
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
        return result, lifecycle
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


def _run_core(ports: Any, *, wrapper_sha256: str, clock: Any = time.monotonic) -> dict[str, object]:
    """Fakeable orchestration; production CLI supplies only fixed Root ports."""

    try:
        source_policy = _validate_source_policy(ports.source_policy())
        if source_policy["profile_id"] != PROFILE_ID:
            raise RootActivationError("v17_source_policy_mismatch")
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
        result, lifecycle = ports.run_fixed_cli(deadline=deadline, cleanup_seconds=MAX_CLEANUP_SECONDS)
        if not _valid_lifecycle(lifecycle):
            raise RootActivationError("cli_lifecycle_unconfirmed")
        if result.get("certification") == "PASS" and lifecycle.get("normal_exit_code") != 0:
            raise RootActivationError("cli_result_lifecycle_mismatch")
        return _validate_v17_payload(result)
    except RootActivationError as error:
        return _blocked(error.reason)
    except Exception:
        # Provider values, filesystem exceptions and private parser messages
        # must never be copied into the public stdout result.
        return _blocked("root_activation_blocked")


class _ProductionPorts:
    """Current V17 source-backed protected reader and fixed Job command."""

    def __init__(self, root: Path, bundle: Any, runner_source: bytes):
        self.root = root
        self.bundle = bundle
        self.issuer = bundle.issuer
        self.owner = bundle.owner
        self.helpers = dict(bundle.helpers)
        self.runner_source = runner_source
        self._api = None
        self._user_profile: Optional[Path] = None
        self._namespace_stack = None
        self._namespace_root: Optional[Path] = None
        self._namespace_collection: Optional[Path] = None
        self._root_claimed = False

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
        runner = self.root / Path(_CASE_RUNNER_RELATIVE)
        return SimpleNamespace(
            argv=(
                str(python),
                "-I",
                "-S",
                "-B",
                str(runner),
                "--live",
                "--profile",
                PROFILE_ID,
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
        result, lifecycle = _run_v17_job(
            backend_module=self.helpers["job_backend"], command=command, deadline=deadline
        )
        return result, lifecycle


def _run_production(wrapper_sha256: str) -> dict[str, object]:
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
        with _verified_v17_sources(root) as (bundle, policy, runner_source):
            ports = _ProductionPorts(root, bundle, runner_source)
            return _run_core(ports, wrapper_sha256=wrapper_sha256)
    except RootActivationError as error:
        return _blocked(error.reason)
    except Exception:
        return _blocked("root_activation_blocked")


def main(argv: Optional[Sequence[str]] = None) -> int:
    """Default-closed public CLI; fake ports are never accepted here."""

    try:
        own_source = _read_own_source()
        expected = _parse_activation_args(list(sys.argv[1:] if argv is None else argv), own_source)
        return _emit(_run_production(expected))
    except RootActivationError as error:
        return _emit(_blocked(error.reason))
    except Exception:
        return _emit(_blocked("root_activation_blocked"))


if __name__ == "__main__":
    raise SystemExit(main())

