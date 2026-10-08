"""Current-invocation local issuer for the SimNow C01 V19 TD read profile.

Importing this module is inert. The fixed operation accepts no caller
credentials, endpoints, receipts, artifacts, or eligibility claims. It uses
only the fixed case profile to begin one bounded local read-only invocation.
Every eligible result is recomputed from the current worker, Job, and private
artifact evidence under this profile's source-pinned closure.
"""

from __future__ import annotations

from contextlib import ExitStack, contextmanager
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import hashlib
import importlib.machinery
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import threading
import time
from types import MappingProxyType, ModuleType
from typing import Any, List, Mapping, Sequence, Tuple


PROFILE_ID = "C01_NATIVE_TD_READ_V19"
CASE_ID = "C01"
MAX_RUN_SECONDS = 90.0
MAX_CLEANUP_SECONDS = 5.0
MAX_PAIR_SELECTION_SECONDS = 30.0
MAX_POST_RUN_VALIDATION_SECONDS = 5.0
MAX_PROFILE_SECONDS = 150.0
MAX_PROJECTION_BYTES = 8192
MAX_CONFIG_BYTES = 256 * 1024
MAX_PRIVATE_AUDIT_BYTES = 4 * 1024 * 1024
MAX_WORKER_PROGRESS_RECORDS = 128
MAX_WORKER_PROGRESS_RECORD_BYTES = 4096
MAX_WORKER_PROGRESS_TOTAL_BYTES = 512 * 1024
MAX_PRIVATE_FAILURE_BYTES = 8 * 1024 * 1024
MAX_PRIVATE_FAILURE_CALLBACKS = 10000
_DIAGNOSTIC_INTENTS_ONLY = False
_FAILURE_CODE_LITERALS = tuple("""
account_economic_field_missing
account_scope_digest_mismatch
account_snapshot_row_count_invalid
account_trading_day_mismatch
auth_login_error_info_unverified
authentication_callback_count_invalid
authentication_error_id_unverified
baseline_artifact_hash_mismatch
connection_generation_changed
credential_binding_digest_mismatch
dependency_manifest_hash_mismatch
dependency_manifest_invalid
dependency_manifest_path_invalid
dependency_manifest_unavailable
dependency_native_payload_rejected
dependency_record_exclusion_mismatch
dependency_record_file_hash_mismatch
dependency_record_file_missing
dependency_record_hash_algorithm_invalid
dependency_record_hash_mismatch
dependency_record_hash_missing
dependency_record_invalid
dependency_record_missing
dependency_record_path_invalid
dependency_record_size_mismatch
dependency_record_unapproved_path
dependency_source_file_count_mismatch
dependency_source_not_recorded
dependency_source_tree_unavailable
duplicate_private_input_key
failure_diagnostic_encoding_failed
failure_diagnostic_size_invalid
final_artifact_hash_mismatch
interpreter_binding_already_loaded
interpreter_binding_runtime_mismatch
interpreter_binding_source_hash_mismatch
interpreter_binding_source_unavailable
interpreter_binding_type_invalid
login_error_id_unverified
login_identity_mismatch
login_terminal_callback_invalid
native_activity_callback_invalid
native_callback_limit_exceeded
native_capture_incomplete
native_close_incomplete
native_close_unavailable
native_credential_field_unavailable
native_flow_path_binding_mismatch
native_lifecycle_descriptor_invalid
native_lifecycle_instrumentation_invalid
native_login_api_type_invalid
native_login_not_ready
native_no_join_release_unverified
native_order_field_missing
native_order_identity_duplicated
native_order_integer_invalid
native_order_quantity_invalid
native_order_status_unknown
native_order_text_invalid
native_projection_field_missing
native_query_callback_unbound
native_query_error_id_unverified
native_query_incomplete
native_query_phase_mismatch
native_query_provenance_binding_invalid
native_query_provenance_unverified
native_query_records_callback_mismatch
native_query_records_unverifiable
native_query_request_missing
native_query_result_type_unverified
native_query_return_code_unverified
native_query_terminal_callback_missing
native_request_allowlist_violation
native_request_field_unavailable
native_request_id_invalid
native_request_invocation_failed
native_request_plan_incomplete
native_request_return_code_unverified
native_request_return_type_invalid
native_response_error_id_malformed
native_response_error_info_invalid
native_response_metadata_invalid
native_response_request_unbound
native_response_scope_mismatch
native_row_key_invalid
native_row_snapshot_failed
native_row_snapshotter_missing
native_row_value_unsupported
native_snapshots_incomplete
non_finite_native_row
open_order_identity_unavailable
order_trading_day_mismatch
owner_acl_create_failed
owner_acl_unverified
owner_sid_unavailable
owner_token_unavailable
pinned_cpython_runtime_required
pinned_ctp_native_hash_mismatch
pinned_ctp_native_missing
pinned_ctp_native_not_recorded
pinned_login_submit_route_unavailable
pinned_native_extension_origin_mismatch
pinned_native_extension_unavailable
pinned_sdk_import_failed
pinned_sdk_import_path_unsafe
pinned_sdk_isolation_required
position_date_unknown
position_decimal_invalid
position_decimal_out_of_bounds
position_decimal_type_invalid
position_direction_unknown
position_exchange_unknown
position_field_missing
position_hedge_unknown
position_instrument_missing
position_integer_quantity_invalid
position_measure_missing
position_session_trading_day_invalid
position_text_invalid
position_trading_day_mismatch
private_directory_not_local
private_directory_root_mismatch
private_directory_unavailable
private_input_credential_invalid
private_input_packet_invalid
private_input_path_invalid
private_input_shape_invalid
private_path_invalid
private_path_unavailable
private_reparse_path_rejected
private_repository_path_rejected
private_run_root_not_fresh
private_run_root_unavailable
process_start_audit_install_failed
process_start_audit_unavailable
progress_intent_write_failed
progress_pair_binding_invalid
progress_record_digest_mismatch
progress_record_encoding_failed
progress_record_limit_exceeded
progress_record_write_failed
progress_run_binding_invalid
progress_stage_invalid
progress_worker_source_binding_invalid
protocol_source_hash_mismatch
protocol_source_unavailable
query_error_id_unverified
query_phase_invalid
query_row_account_identity_unavailable
query_row_account_mismatch
query_row_broker_mismatch
query_row_investor_mismatch
query_terminal_callback_missing
readonly_client_class_invalid
readonly_join_guard_invalid
readonly_join_method_unavailable
readonly_join_observer_descriptor_invalid
readonly_native_join_forbidden
readonly_no_join_start_unverified
readonly_no_join_state_invalid
required_native_methods_missing
sdk_client_generation_invalid
sdk_client_unbound
sdk_login_scope_mismatch
sdk_record_file_hash_mismatch
sdk_record_file_missing
sdk_record_hash_algorithm_invalid
sdk_record_hash_mismatch
sdk_record_hash_missing
sdk_record_invalid
sdk_record_missing
sdk_record_path_invalid
sdk_record_size_mismatch
sdk_site_packages_missing
sdk_source_file_count_mismatch
sdk_source_not_recorded
sdk_source_tree_unavailable
six_virtual_module_kind_invalid
six_virtual_module_missing
six_virtual_moved_module_changed
six_virtual_moved_module_origin_missing
six_virtual_namespace_changed
six_virtual_parse_module_changed
six_virtual_source_module_changed
snapshot_create_failed
snapshot_directory_create_failed
snapshot_flush_failed
snapshot_size_invalid
snapshot_write_failed
stage_intent_descriptor_invalid
stage_intent_encoding_failed
stage_intent_frame_limit_exceeded
stage_intent_pair_binding_invalid
stage_intent_record_limit_exceeded
stage_intent_run_binding_invalid
stage_intent_source_binding_invalid
stage_intent_total_limit_exceeded
stage_intent_value_invalid
stage_intent_write_failed
stage_intent_writer_invalid
start_precheck_descriptor_invalid
start_precheck_instrumentation_invalid
td_front_binding_mismatch
td_front_invalid
verified_worker_source_hash_missing
windows_private_acl_required
worker_frame_size_invalid
""".split())
_FAILURE_CODE_ORDINALS = MappingProxyType(
    {value: index for index, value in enumerate(_FAILURE_CODE_LITERALS, start=1)}
)
_FAILURE_CODE_UNCLASSIFIED_ORDINAL = 0
_FAILURE_CODE_ORDINAL_MAX = len(_FAILURE_CODE_LITERALS)

# Local source pins are reviewed identifiers, not an external signing root.
# The exact worker source, SDK RECORDs, and native payload are then checked by
# the frozen worker before it imports any SDK/native module.
_OWNER_SHA256 = "ee492f115c60ca14f770a055061014f30b7b9cc1cecdfd09cae17f75aabf55e9"
_CASE_CONTRACT_SHA256 = "33d60824f780784f0c391a8212816c6167dd7485dec5b9fc0b461b28e6b4adca"
_CASE_STRATEGY_SHA256 = "c88501fda1ce83cebb334b58566776bee5154a5cfea1c5cc22d717a2e09d3f17"
_ENVREF_TEMPLATE_SHA256 = "debc71d75b4e04c4e64c38750cdfa2101dc69585ef7898a290c721d882f51db2"
_WORKER_SHA256 = "66666d2addc3bddbf0f13a9a30fab9fea83479d7cac7328879552e13baea5a66"
_PROTOCOL_SHA256 = "c48b41272ae6378060b0b65188b56ef613f001b53d13db7aceaf13489d398160"
_CONTRACT_SHA256 = "19d8b13bda11e54a5ca037387b6abc884035ec02c05fb099f2398b99319d8fb0"
_SUPERVISOR_SHA256 = "daf2cf99cbc5d977e27f59efb0f27087abdf3493c9d959d5c3d253744f869da1"
_DEPENDENCY_MANIFEST_SHA256 = "7cb851df481066ee7622aea0bdd87863d6e04d3372fb520e7685a241411f2324"
_PRIVATE_HELPER_SHA256 = "b866194bdc56d91cc7a6678e83b0af8e4e018ee53a2c136325344c2ee8a5ecfd"
_R3_CLI_HELPER_SHA256 = "62b96a9040d530c8ec592471f0595154fb60239ca03bd6d3b56a6c094dfc7c76"
_SOURCE_MANIFEST_PATH = "backtrader_runtime/certification_simnow_c01_native_td_read_v19.sources.json"
_SOURCE_MANIFEST_SHA256 = "fec7bc9d0ea5f90c1b2d0a7b8ec8bb663422ff0c2a8763fece6427a45091e5d1"
_ADMISSION_SCHEMA_PATH = (
    "backtrader_runtime/certification_simnow_c01_native_td_read_v19.admission.schema.json"
)
_ADMISSION_SCHEMA_SHA256 = "95f0c05c0b6e3f80f9b6b0d7a23532ed28ddc84ffc7e8f03cfe827f4a6db30c2"
_INTERPRETER_BINDING_SHA256 = "a38d00ecfbc7a777edab4b9d090be49ef03a94e7c23340dfe95366bacfd05494"
_INTERPRETER_BINDING_PATH = "backtrader_runtime/certification_simnow_c01_interpreter_binding_v1.py"
_INTERPRETER_BINDING_MODULE_NAME = "_c01_pinned_interpreter_binding"
_CONFIG_RELATIVE = "examples/000_live_certification/simnow_penetration/config.yaml"
_CASE_RUNNER_RELATIVE = "examples/000_live_certification/simnow_penetration/cases/C01/run_v19.py"
_ADMISSION_BOUND_SOURCE_PATHS = (
    "backtrader_runtime/certification_simnow_c01_native_td_read_v19.py",
    _CASE_RUNNER_RELATIVE,
)
_ADMISSION_ROOT_NAME = "simnow-c01-native-td-read-v19"
_ADMISSION_COLLECTION_NAME = "admissions"
_ADMISSION_CLAIM_NAME = "claimed"
_ADMISSION_SCHEMA = "simnow.c01.native_td_read_v19.admission.v1"
_CONSUMED_SCHEMA = "simnow.c01.native_td_read_v19.consumed.v1"
_CLAIM_SCHEMA = "simnow.c01.native_td_read_v19.claim.v1"
_ADMISSION_MAX_BYTES = 16 * 1024
_ADMISSION_MAX_ENTRIES = 128
_ADMISSION_MAX_TTL_SECONDS = 600
_ADMISSION_DIRECTORY_ACCESS = 0x80020080  # GENERIC_READ | READ_CONTROL | FILE_READ_ATTRIBUTES
_ADMISSION_ID_RE = re.compile(r"[0-9a-f]{32}\Z")
_ADMISSION_TIME_RE = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z\Z")
_ENV_NAMES = frozenset(
    {
        "SIMNOW_USER_ID",
        "SIMNOW_PASSWORD",
        "CTP_BROKER_ID",
        "CTP_APP_ID",
        "CTP_AUTH_CODE",
    }
)
_AMBIENT_SECRET_AND_FRONT_NAMES = frozenset(
    {
        "SIMNOW_USER_ID",
        "SIMNOW_PASSWORD",
        "CTP_BROKER_ID",
        "CTP_APP_ID",
        "CTP_AUTH_CODE",
        "CTP_MD_FRONT",
        "CTP_TD_FRONT",
    }
)
_FIELD_ENV_NAMES = {
    "broker_id": "CTP_BROKER_ID",
    "user_id": "SIMNOW_USER_ID",
    "password": "SIMNOW_PASSWORD",
    "app_id": "CTP_APP_ID",
    "auth_code": "CTP_AUTH_CODE",
}
_ENV_VALUE_MAX_BYTES = {
    "broker_id": 10,
    "user_id": 15,
    "password": 40,
    "app_id": 32,
    "auth_code": 16,
}
_SAFE_REASON = re.compile(r"[a-z0-9_:-]{1,96}\Z")
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
_FRESH_PAIR_HANDOFF_FAILURES = MappingProxyType(
    {
        "no_current_transport_candidate": "fresh_pair_no_transport_candidate",
        "current_transport_observation_unavailable": "fresh_pair_probe_unavailable",
        "current_transport_observation_invalid": "fresh_pair_probe_invalid",
        "current_transport_observation_expired": "fresh_pair_probe_invalid",
        "current_transport_pair_binding_invalid": "fresh_pair_handoff_rejected",
        "transport_handoff_expired": "fresh_pair_handoff_rejected",
        "transport_handoff_custody_mismatch": "fresh_pair_handoff_rejected",
        "transport_handoff_projection_mismatch": "fresh_pair_handoff_rejected",
        "transport_handoff_already_consumed": "fresh_pair_handoff_rejected",
        "transport_handoff_clock_invalid": "fresh_pair_handoff_rejected",
    }
)
_FRESH_PAIR_SELECTION_SOURCE = "scripts.ctp_000_front_handoff.SelectedFrontPair"
_RESULT_FACTORY = object()
_OWNER_MODULE_NAME = "backtrader_runtime._c01_native_td_read_v7_owner"
_ISSUER_LOCK = threading.Lock()
_SHA256_RE = re.compile(r"[0-9a-f]{64}\Z")
_PROFILE_CONTRACT = {
    "profile_id": PROFILE_ID,
    "case_id": CASE_ID,
    "scope": "td_auth_login_account_read_only",
    "requests": [
        "authenticate",
        "login",
        "baseline_orders",
        "baseline_positions",
        "baseline_funds",
        "final_orders",
        "final_positions",
        "final_funds",
    ],
    "native_stop_required": True,
    "native_join_required": False,
    "native_lifecycle_mode": "NO_JOIN_RELEASE_RETURNED",
    "md_sdk_session": False,
    "front_transport_probe_candidates": 8,
    "order_insert_requests": 0,
    "order_cancel_requests": 0,
    "diagnostic_intents_only": _DIAGNOSTIC_INTENTS_ONLY,
    "case_receipt_authority": "none",
}
PROFILE_CONTRACT_SHA256 = hashlib.sha256(
    json.dumps(
        _PROFILE_CONTRACT,
        ensure_ascii=True,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("ascii")
).hexdigest()


def _verify_source_manifest(root: Path, owner: ModuleType) -> None:
    raw = _read_fixed_source(root, _SOURCE_MANIFEST_PATH, _SOURCE_MANIFEST_SHA256)
    try:
        manifest = json.loads(raw.decode("ascii"), object_pairs_hook=_strict_object)
    except Exception:
        raise _IssuerError("source_manifest_invalid") from None
    if type(manifest) is not dict or set(manifest) != {
        "schema",
        "profile_id",
        "source_files",
        "admission_bound_files",
    }:
        raise _IssuerError("source_manifest_invalid")
    expected_files = dict(owner._SOURCE_PINS)
    expected_files.update(
        {
            "backtrader_runtime/certification_simnow_c01_v7_owner.py": _OWNER_SHA256,
            "examples/000_live_certification/simnow_penetration/case_contracts/C01.yaml": (
                _CASE_CONTRACT_SHA256
            ),
            "examples/000_live_certification/simnow_penetration/cases/C01/C01_strategy.py": (
                _CASE_STRATEGY_SHA256
            ),
            "examples/000_live_certification/simnow_penetration/config.private.yaml.template": (
                _ENVREF_TEMPLATE_SHA256
            ),
            _ADMISSION_SCHEMA_PATH: _ADMISSION_SCHEMA_SHA256,
        }
    )
    if (
        manifest.get("schema") != "simnow.c01.native_td_read_v19.source_manifest.v1"
        or manifest.get("profile_id") != PROFILE_ID
        or type(manifest.get("source_files")) is not dict
        or manifest["source_files"] != expected_files
        or manifest.get("admission_bound_files") != list(_ADMISSION_BOUND_SOURCE_PATHS)
    ):
        raise _IssuerError("source_manifest_mismatch")


class _IssuerError(ValueError):
    """Fixed local failure categories only; never carries private values."""


class _AdmissionLeaseFailure(_IssuerError):
    """Unexpected admission-lease failure with finite, value-free diagnostics."""

    def __init__(
        self,
        stage: str,
        failure_class: str,
        reason: str = "admission_lease_failed",
    ):
        if stage not in _ADMISSION_FAILURE_STAGES or stage == "none":
            stage = "other"
        if failure_class not in _ADMISSION_FAILURE_CLASSES or failure_class == "none":
            failure_class = "other"
        if reason not in {"admission_lease_failed", "admission_source_handle_close_failed"}:
            reason = "admission_lease_failed"
        super().__init__(reason)
        self.stage = stage
        self.failure_class = failure_class


def _admission_failure_class(error: BaseException) -> str:
    """Reduce an exception to a closed public category without reading its text."""

    if isinstance(error, PermissionError):
        return "permission"
    if isinstance(error, OSError):
        return "os"
    if isinstance(error, (TypeError, ValueError)):
        return "type_value"
    if isinstance(error, RuntimeError):
        return "runtime"
    return "other"


@dataclass(frozen=True, init=False)
class C01NativeTdReadV19Result:
    status: str
    reason: str
    profile: str = PROFILE_ID
    case_id: str = CASE_ID
    writes: int = 0
    admission_failure_stage: str = "none"
    admission_failure_class: str = "none"
    worker_observation: Mapping[str, Any] | None = None
    post_worker_failure_stage: str = "none"
    post_worker_failure_code: str = "none"

    def __init__(
        self,
        status: str,
        reason: str,
        profile: str = PROFILE_ID,
        case_id: str = CASE_ID,
        writes: int = 0,
        admission_failure_stage: str = "none",
        admission_failure_class: str = "none",
        worker_observation: Mapping[str, Any] | None = None,
        post_worker_failure_stage: str = "none",
        post_worker_failure_code: str = "none",
        *,
        _factory: Any = None,
    ) -> None:
        if _factory is not _RESULT_FACTORY:
            raise ValueError("c01_native_td_result_factory_required")
        if (
            status not in {"PASS", "BLOCKED"}
            or profile != PROFILE_ID
            or case_id != CASE_ID
            or writes != 0
            or type(reason) is not str
            or not _SAFE_REASON.fullmatch(reason)
            or admission_failure_stage not in _ADMISSION_FAILURE_STAGES
            or admission_failure_class not in _ADMISSION_FAILURE_CLASSES
            or ((admission_failure_stage == "none") != (admission_failure_class == "none"))
            or (
                admission_failure_stage != "none"
                and (
                    status != "BLOCKED"
                    or reason
                    not in {"admission_lease_failed", "admission_source_handle_close_failed"}
                )
            )
            or (
                reason in {"admission_lease_failed", "admission_source_handle_close_failed"}
                and admission_failure_stage == "none"
            )
            or type(post_worker_failure_stage) is not str
            or post_worker_failure_stage not in _POST_WORKER_FAILURE_STAGES
            or type(post_worker_failure_code) is not str
            or post_worker_failure_code not in _POST_WORKER_FAILURE_CODES
            or ((post_worker_failure_stage == "none") != (post_worker_failure_code == "none"))
            or (
                post_worker_failure_stage == "verify_tree"
                and post_worker_failure_code
                not in (_OWNER_VERIFY_TREE_FAILURE_CODES | {"unclassified_owner_error"})
            )
            or (
                post_worker_failure_stage == "read_snapshot_artifacts"
                and post_worker_failure_code
                not in (_OWNER_SNAPSHOT_READ_FAILURE_CODES | {"unclassified_owner_error"})
            )
            or (
                post_worker_failure_stage != "none"
                and (status != "BLOCKED" or reason != "candidate_owner_validation_failed")
            )
            or (
                reason == "candidate_owner_validation_failed"
                and post_worker_failure_stage == "none"
            )
        ):
            raise ValueError("c01_native_td_result_invalid")
        safe_observation = _validate_worker_observation(worker_observation)
        object.__setattr__(self, "status", status)
        object.__setattr__(self, "reason", reason)
        object.__setattr__(self, "profile", profile)
        object.__setattr__(self, "case_id", case_id)
        object.__setattr__(self, "writes", writes)
        object.__setattr__(self, "admission_failure_stage", admission_failure_stage)
        object.__setattr__(self, "admission_failure_class", admission_failure_class)
        object.__setattr__(self, "worker_observation", safe_observation)
        object.__setattr__(self, "post_worker_failure_stage", post_worker_failure_stage)
        object.__setattr__(self, "post_worker_failure_code", post_worker_failure_code)

    def to_dict(self) -> dict[str, Any]:
        return {
            "case_id": CASE_ID,
            "certification": self.status,
            "mode": PROFILE_ID,
            "profile": PROFILE_ID,
            "reason": self.reason,
            "write_policy": "NO_WRITE",
            "writes": 0,
            "admission_failure_stage": self.admission_failure_stage,
            "admission_failure_class": self.admission_failure_class,
            "worker_observation": _validate_worker_observation(self.worker_observation),
            "post_worker_failure_stage": self.post_worker_failure_stage,
            "post_worker_failure_code": self.post_worker_failure_code,
        }


def _blocked(
    reason: str,
    *,
    admission_failure_stage: str = "none",
    admission_failure_class: str = "none",
    worker_observation: Mapping[str, Any] | None = None,
    post_worker_failure_stage: str = "none",
    post_worker_failure_code: str = "none",
) -> C01NativeTdReadV19Result:
    safe_reason = (
        reason
        if type(reason) is str and _SAFE_REASON.fullmatch(reason)
        else "issuer_internal_error"
    )
    return C01NativeTdReadV19Result(
        "BLOCKED",
        safe_reason,
        admission_failure_stage=admission_failure_stage,
        admission_failure_class=admission_failure_class,
        worker_observation=worker_observation,
        post_worker_failure_stage=post_worker_failure_stage,
        post_worker_failure_code=post_worker_failure_code,
        _factory=_RESULT_FACTORY,
    )


def _owner_failure_code(owner: ModuleType, error: BaseException, stage: str) -> str:
    """Map only the exact loaded owner's fixed code into a closed stage enum."""

    allowed = (
        _OWNER_VERIFY_TREE_FAILURE_CODES
        if stage == "verify_tree"
        else _OWNER_SNAPSHOT_READ_FAILURE_CODES
        if stage == "read_snapshot_artifacts"
        else frozenset()
    )
    if type(error) is not owner._OwnerError:
        return "unclassified_owner_error"
    args = error.args
    if type(args) is tuple and len(args) == 1 and type(args[0]) is str and args[0] in allowed:
        return args[0]
    return "unclassified_owner_error"


def _repo_root() -> Path:
    try:
        root = Path(__file__).resolve(strict=True).parents[1]
    except Exception:
        raise _IssuerError("issuer_source_unavailable") from None
    if not root.is_absolute() or not root.is_dir():
        raise _IssuerError("issuer_source_unavailable")
    return root


def _read_fixed_source(root: Path, relative: str, expected_sha256: str) -> bytes:
    path = root / Path(relative)
    try:
        info = path.lstat()
        attributes = getattr(info, "st_file_attributes", 0)
        if path.is_symlink() or attributes & 0x400 or not path.is_file():
            raise _IssuerError("pinned_source_not_regular")
        if info.st_size > 8 * 1024 * 1024:
            raise _IssuerError("pinned_source_size_invalid")
        with path.open("rb") as stream:
            raw = stream.read(8 * 1024 * 1024 + 1)
    except _IssuerError:
        raise
    except Exception:
        raise _IssuerError("pinned_source_unavailable") from None
    if len(raw) > 8 * 1024 * 1024:
        raise _IssuerError("pinned_source_size_invalid")
    if hashlib.sha256(raw).hexdigest() != expected_sha256:
        raise _IssuerError("pinned_source_digest_mismatch")
    return raw


def _verify_public_profile_sources(root: Path) -> None:
    _read_fixed_source(root, _INTERPRETER_BINDING_PATH, _INTERPRETER_BINDING_SHA256)
    _read_fixed_source(
        root,
        "examples/000_live_certification/simnow_penetration/case_contracts/C01.yaml",
        _CASE_CONTRACT_SHA256,
    )
    _read_fixed_source(
        root,
        "examples/000_live_certification/simnow_penetration/cases/C01/C01_strategy.py",
        _CASE_STRATEGY_SHA256,
    )
    _read_fixed_source(
        root,
        "examples/000_live_certification/simnow_penetration/config.private.yaml.template",
        _ENVREF_TEMPLATE_SHA256,
    )
    _read_fixed_source(root, _ADMISSION_SCHEMA_PATH, _ADMISSION_SCHEMA_SHA256)


def _load_frozen_owner(root: Path) -> ModuleType:
    raw = _read_fixed_source(
        root,
        "backtrader_runtime/certification_simnow_c01_v7_owner.py",
        _OWNER_SHA256,
    )
    name = _OWNER_MODULE_NAME
    if name in sys.modules:
        raise _IssuerError("owner_module_already_loaded")
    module = ModuleType(name)
    module.__file__ = str(root / "backtrader_runtime" / "certification_simnow_c01_v7_owner.py")
    module.__package__ = "backtrader_runtime"
    module.__loader__ = None
    module.__spec__ = importlib.machinery.ModuleSpec(name, loader=None)
    sys.modules[name] = module
    try:
        exec(compile(raw, module.__file__, "exec", dont_inherit=True), module.__dict__)
    except Exception:
        sys.modules.pop(name, None)
        raise _IssuerError("owner_source_compile_failed") from None
    return module


def _consumer_matches() -> bool:
    module = None
    try:
        root = _repo_root()
        raw = _read_fixed_source(root, _INTERPRETER_BINDING_PATH, _INTERPRETER_BINDING_SHA256)
        if _INTERPRETER_BINDING_MODULE_NAME in sys.modules:
            return False
        module = ModuleType(_INTERPRETER_BINDING_MODULE_NAME)
        module.__file__ = str(root / Path(_INTERPRETER_BINDING_PATH))
        module.__package__ = ""
        sys.modules[_INTERPRETER_BINDING_MODULE_NAME] = module
        exec(compile(raw, module.__file__, "exec", dont_inherit=True), module.__dict__)
        return module.verify_current_runtime() is True
    except Exception:
        return False
    finally:
        if module is not None and sys.modules.get(_INTERPRETER_BINDING_MODULE_NAME) is module:
            sys.modules.pop(_INTERPRETER_BINDING_MODULE_NAME, None)


def _strict_object(pairs: List[Tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise _IssuerError("private_config_duplicate_key")
        result[key] = value
    return result


def _strict_source_object(pairs: List[Tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise _IssuerError("admission_duplicate_key")
        result[key] = value
    return result


@dataclass(frozen=True, repr=False)
class _C01V19Admission:
    admission_id: str
    not_before_utc: datetime
    expires_at_utc: datetime
    bindings: Mapping[str, str]
    configured_front_pair_count: int
    admission_sha256: str = ""
    claim_sha256: str = ""
    consumed_sha256: str = ""

    def __repr__(self) -> str:
        return "_C01V19Admission(<private one-shot registration>)"

    def active(self, now: datetime | None = None) -> bool:
        current = now or datetime.now(timezone.utc)
        return self.not_before_utc <= current <= self.expires_at_utc


def _required_admission_bindings(
    *, issuer_source_sha256: str, case_runner_source_sha256: str
) -> dict[str, str]:
    return {
        "case_runner_source_sha256": case_runner_source_sha256,
        "issuer_source_sha256": issuer_source_sha256,
        "source_manifest_sha256": _SOURCE_MANIFEST_SHA256,
        "profile_contract_sha256": PROFILE_CONTRACT_SHA256,
        "owner_source_sha256": _OWNER_SHA256,
        "worker_source_sha256": _WORKER_SHA256,
        "protocol_source_sha256": _PROTOCOL_SHA256,
        "contract_source_sha256": _CONTRACT_SHA256,
        "supervisor_source_sha256": _SUPERVISOR_SHA256,
        "sdk_dependency_manifest_sha256": _DEPENDENCY_MANIFEST_SHA256,
        "interpreter_binding_source_sha256": _INTERPRETER_BINDING_SHA256,
        "case_contract_sha256": _CASE_CONTRACT_SHA256,
        "case_strategy_sha256": _CASE_STRATEGY_SHA256,
        "envref_template_sha256": _ENVREF_TEMPLATE_SHA256,
    }


def _parse_profile_admission(
    raw: bytes,
    *,
    expected_bindings: Mapping[str, str],
    now: datetime | None = None,
) -> _C01V19Admission:
    if type(raw) is not bytes or not 0 < len(raw) <= _ADMISSION_MAX_BYTES:
        raise _IssuerError("admission_size_invalid")
    try:
        value = json.loads(
            raw.decode("ascii"),
            object_pairs_hook=_strict_source_object,
            parse_constant=lambda _item: (_ for _ in ()).throw(
                _IssuerError("admission_nonfinite_number")
            ),
        )
    except _IssuerError:
        raise
    except Exception:
        raise _IssuerError("admission_invalid") from None
    try:
        canonical = (
            json.dumps(
                value,
                ensure_ascii=True,
                allow_nan=False,
                sort_keys=True,
                separators=(",", ":"),
            )
            + "\n"
        ).encode("ascii")
    except Exception:
        raise _IssuerError("admission_invalid") from None
    if canonical != raw:
        raise _IssuerError("admission_not_canonical")
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
    }
    if type(value) is not dict or set(value) != {
        "schema",
        "profile_id",
        "case_id",
        "admission_id",
        "status",
        "not_before_utc",
        "expires_at_utc",
        "scope",
        "bindings",
    }:
        raise _IssuerError("admission_schema_invalid")
    if (
        value["schema"] != _ADMISSION_SCHEMA
        or value["profile_id"] != PROFILE_ID
        or value["case_id"] != CASE_ID
        or type(value["admission_id"]) is not str
        or not _ADMISSION_ID_RE.fullmatch(value["admission_id"])
        or value["status"] != "ACTIVE"
        or type(value["scope"]) is not dict
        or set(value["scope"]) != set(scope) | {"configured_front_pair_count"}
        or type(value["scope"].get("configured_front_pair_count")) is not int
        or not 1 <= value["scope"].get("configured_front_pair_count", 0) <= 8
        or any(
            type(value["scope"].get(key)) is not type(expected)
            or value["scope"].get(key) != expected
            for key, expected in scope.items()
        )
        or type(value["bindings"]) is not dict
        or any(
            type(digest) is not str or not _SHA256_RE.fullmatch(digest)
            for digest in value["bindings"].values()
        )
    ):
        raise _IssuerError("admission_binding_mismatch")
    dynamic_bindings = {
        "config_source_sha256",
        "account_scope_sha256",
        "credential_binding_sha256",
    }
    if set(value["bindings"]) != set(expected_bindings) | dynamic_bindings or any(
        value["bindings"].get(key) != expected for key, expected in expected_bindings.items()
    ):
        raise _IssuerError("admission_binding_mismatch")
    if (
        type(value["not_before_utc"]) is not str
        or not _ADMISSION_TIME_RE.fullmatch(value["not_before_utc"])
        or type(value["expires_at_utc"]) is not str
        or not _ADMISSION_TIME_RE.fullmatch(value["expires_at_utc"])
    ):
        raise _IssuerError("admission_time_invalid")
    try:
        not_before = datetime.strptime(value["not_before_utc"], "%Y-%m-%dT%H:%M:%SZ").replace(
            tzinfo=timezone.utc
        )
        expires_at = datetime.strptime(value["expires_at_utc"], "%Y-%m-%dT%H:%M:%SZ").replace(
            tzinfo=timezone.utc
        )
    except Exception:
        raise _IssuerError("admission_time_invalid") from None
    current = now or datetime.now(timezone.utc)
    ttl = (expires_at - not_before).total_seconds()
    if ttl <= 0 or ttl > _ADMISSION_MAX_TTL_SECONDS:
        raise _IssuerError("admission_ttl_invalid")
    if current < not_before:
        raise _IssuerError("admission_not_yet_valid")
    if current > expires_at:
        raise _IssuerError("admission_expired")
    return _C01V19Admission(
        admission_id=value["admission_id"],
        not_before_utc=not_before,
        expires_at_utc=expires_at,
        bindings=MappingProxyType(dict(value["bindings"])),
        configured_front_pair_count=value["scope"]["configured_front_pair_count"],
        admission_sha256=hashlib.sha256(raw).hexdigest(),
    )


def _load_admission_helpers(root: Path) -> tuple[ModuleType, ModuleType]:
    private_raw = _read_fixed_source(
        root,
        "backtrader_runtime/certification_roundtrip_private.py",
        _PRIVATE_HELPER_SHA256,
    )
    cli_raw = _read_fixed_source(
        root,
        "backtrader_runtime/certification_binance_roundtrip_r3_cli.py",
        _R3_CLI_HELPER_SHA256,
    )
    modules = []
    for name, relative, raw in (
        (
            "_c01_v3_admission_private_helper",
            "backtrader_runtime/certification_roundtrip_private.py",
            private_raw,
        ),
        (
            "_c01_v3_admission_r3_cli_helper",
            "backtrader_runtime/certification_binance_roundtrip_r3_cli.py",
            cli_raw,
        ),
    ):
        module = ModuleType(name)
        module.__file__ = str(root / Path(relative))
        module.__package__ = ""
        if name in sys.modules:
            raise _IssuerError("admission_helper_already_loaded")
        sys.modules[name] = module
        try:
            exec(compile(raw, module.__file__, "exec", dont_inherit=True), module.__dict__)
        except Exception:
            if sys.modules.get(name) is module:
                sys.modules.pop(name, None)
            raise _IssuerError("admission_helper_compile_failed") from None
        if sys.modules.get(name) is module:
            sys.modules.pop(name, None)
        modules.append(module)
    return modules[0], modules[1]


def _held_source_digest(
    path: Path,
    *,
    private: ModuleType,
    r3_cli: ModuleType,
    retained: ExitStack,
) -> str:
    api = private._api()
    try:
        retained.enter_context(r3_cli._credential_ancestor_locks(path, private))
        handle, _identity = retained.enter_context(r3_cli._locked_readonly_file(path, private, api))
        raw = r3_cli._read_bounded_handle(api, handle, 2 * 1024 * 1024)
    except Exception:
        raise _IssuerError("admission_source_lease_failed") from None
    return hashlib.sha256(raw).hexdigest()


def _bounded_namespace_children(path: Path, *, maximum: int, reason: str) -> tuple[Path, ...]:
    children = []
    try:
        for child in path.iterdir():
            if len(children) >= maximum:
                raise _IssuerError(reason)
            children.append(child)
    except _IssuerError:
        raise
    except Exception:
        raise _IssuerError(reason) from None
    return tuple(children)


@contextmanager
def _admission_directory_ancestor_locks(path: Path, private: ModuleType, api: Any):
    """Hold directory ancestors with read access and deny-delete sharing.

    The shared credential helper intentionally opens ancestors for metadata
    only. The V19 admission namespace needs a stronger held handle: GENERIC_READ
    is requested and the pinned private API keeps its fixed share mask at
    FILE_SHARE_READ | FILE_SHARE_WRITE (without FILE_SHARE_DELETE). Keep this
    route-owned so the shared helper's other callers are unchanged.
    """

    path = private._path(Path(path))
    with ExitStack() as stack:
        for ancestor in reversed(path.parents):
            stack.enter_context(
                api.opened(
                    ancestor,
                    directory=True,
                    access=_ADMISSION_DIRECTORY_ACCESS,
                )
            )
        yield


def _open_admission_directory(api: Any, path: Path):
    return api.opened(
        path,
        directory=True,
        access=_ADMISSION_DIRECTORY_ACCESS,
    )


def _consumed_document(admission: _C01V19Admission, issuer_source_sha256: str) -> bytes:
    payload = {
        "schema": _CONSUMED_SCHEMA,
        "profile_id": PROFILE_ID,
        "case_id": CASE_ID,
        "admission_id": admission.admission_id,
        "issuer_source_sha256": issuer_source_sha256,
        "source_manifest_sha256": _SOURCE_MANIFEST_SHA256,
        "consumed_at_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }
    return json.dumps(
        payload, ensure_ascii=True, allow_nan=False, sort_keys=True, separators=(",", ":")
    ).encode("ascii")


def _claim_document(admission: _C01V19Admission, issuer_source_sha256: str) -> bytes:
    payload = {
        "schema": _CLAIM_SCHEMA,
        "profile_id": PROFILE_ID,
        "case_id": CASE_ID,
        "admission_id": admission.admission_id,
        "issuer_source_sha256": issuer_source_sha256,
        "source_manifest_sha256": _SOURCE_MANIFEST_SHA256,
        "claimed_at_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }
    return json.dumps(
        payload, ensure_ascii=True, allow_nan=False, sort_keys=True, separators=(",", ":")
    ).encode("ascii")


def _rewind_locked_read_handle(private: ModuleType, api: Any, handle: Any) -> bool:
    """Reset one retained read handle before its bounded source recheck."""

    try:
        ctypes_module = private.C
        wintypes_module = private.W
        pointer_type = ctypes_module.c_longlong
        set_pointer = api.kernel.SetFilePointerEx
        set_pointer.argtypes = [
            wintypes_module.HANDLE,
            pointer_type,
            ctypes_module.POINTER(pointer_type),
            wintypes_module.DWORD,
        ]
        set_pointer.restype = wintypes_module.BOOL
        new_position = pointer_type()
        if not set_pointer(handle, pointer_type(0), ctypes_module.byref(new_position), 0):
            return False
        return new_position.value == 0
    except Exception:
        return False


@contextmanager
def _profile_admission_lease(root: Path, issuer_module: ModuleType):
    """Consume one current root-created registration before profile inputs load.

    Only the two fixed private-path helpers are compiled to read/lock the
    protected registration. The issuer, case runner, profile manifest, SDK,
    worker and interpreter binding must all match that registration before a
    durable CREATE_NEW consumed namespace is made.
    """

    private = None
    r3_cli = None
    modules = ()
    source_stack = ExitStack()
    stage = "helper_load"
    try:
        private, r3_cli = _load_admission_helpers(root)
        modules = (private, r3_cli)
        stage = "helper_registration"
        if any(module.__name__ in sys.modules for module in modules):
            raise _IssuerError("admission_helper_already_loaded")
        for module in modules:
            sys.modules[module.__name__] = module

        stage = "known_folder"
        api = private._api()
        local_app_data = Path(r3_cli._known_local_app_data()).resolve(strict=True)
        user_profile_text = os.environ.get("USERPROFILE")
        if type(user_profile_text) is not str or not user_profile_text:
            raise _IssuerError("admission_user_profile_unavailable")
        user_profile = private._path(Path(user_profile_text))
        user_profile_resolved = user_profile.resolve(strict=True)
        if (
            not user_profile.is_absolute()
            or not user_profile.is_dir()
            or os.path.normcase(str(local_app_data.parents[1]))
            != os.path.normcase(str(user_profile_resolved))
        ):
            raise _IssuerError("admission_known_folder_mismatch")

        stage = "issuer_source_lock"
        expected_issuer_path = private._path(
            root / "backtrader_runtime" / "certification_simnow_c01_native_td_read_v19.py"
        )
        issuer_path = private._path(Path(issuer_module.__file__).resolve(strict=True))
        if os.path.normcase(str(issuer_path)) != os.path.normcase(str(expected_issuer_path)):
            raise _IssuerError("admission_issuer_path_mismatch")
        expected_issuer = issuer_module.__dict__.get("__c01_source_sha256__", "")
        issuer_digest = _held_source_digest(
            issuer_path,
            private=private,
            r3_cli=r3_cli,
            retained=source_stack,
        )
        if (
            type(expected_issuer) is not str
            or not _SHA256_RE.fullmatch(expected_issuer)
            or issuer_digest != expected_issuer
        ):
            raise _IssuerError("admission_issuer_source_mismatch")
        stage = "runner_source_lock"
        runner_path = private._path(root / Path(_CASE_RUNNER_RELATIVE))
        runner_digest = _held_source_digest(
            runner_path,
            private=private,
            r3_cli=r3_cli,
            retained=source_stack,
        )
        expected_bindings = _required_admission_bindings(
            issuer_source_sha256=issuer_digest,
            case_runner_source_sha256=runner_digest,
        )

        stage = "namespace_lock"
        root_dir = private._path(local_app_data / _ADMISSION_ROOT_NAME)
        collection_dir = private._path(root_dir / _ADMISSION_COLLECTION_NAME)
        sid = api.current_sid()
        with ExitStack() as stack:
            stack.enter_context(_admission_directory_ancestor_locks(collection_dir, private, api))
            root_handle = stack.enter_context(_open_admission_directory(api, root_dir))
            api.verify_acl(root_handle, sid, directory=True)
            collection_handle = stack.enter_context(_open_admission_directory(api, collection_dir))
            api.verify_acl(collection_handle, sid, directory=True)
            stage = "namespace_scan"
            entries = _bounded_namespace_children(
                collection_dir,
                maximum=_ADMISSION_MAX_ENTRIES,
                reason="admission_namespace_limit",
            )
            if any(entry.name == _ADMISSION_CLAIM_NAME for entry in entries):
                raise _IssuerError("admission_profile_already_consumed")
            pending = []
            for entry in entries:
                if not _ADMISSION_ID_RE.fullmatch(entry.name):
                    raise _IssuerError("admission_namespace_invalid")
                entry = private._path(entry)
                directory_handle = stack.enter_context(_open_admission_directory(api, entry))
                api.verify_acl(directory_handle, sid, directory=True)
                contents = _bounded_namespace_children(
                    entry,
                    maximum=2,
                    reason="admission_namespace_invalid",
                )
                content_names = {item.name for item in contents}
                if content_names == {"admission.json"}:
                    pending.append((entry, directory_handle))
                elif content_names == {"admission.json", "consumed"}:
                    consumed = private._path(entry / "consumed")
                    consumed_handle = stack.enter_context(_open_admission_directory(api, consumed))
                    api.verify_acl(consumed_handle, sid, directory=True)
                    if {
                        item.name
                        for item in _bounded_namespace_children(
                            consumed,
                            maximum=1,
                            reason="admission_consumed_marker_invalid",
                        )
                    } != {"consumed.json"}:
                        raise _IssuerError("admission_consumed_marker_invalid")
                    marker_path = private._path(consumed / "consumed.json")
                    marker_handle, _marker_identity = stack.enter_context(
                        r3_cli._locked_readonly_file(marker_path, private, api)
                    )
                    api.verify_acl(marker_handle, sid, directory=False)
                    marker_raw = r3_cli._read_bounded_handle(api, marker_handle, 4096)
                    try:
                        marker = json.loads(
                            marker_raw.decode("ascii"),
                            object_pairs_hook=_strict_source_object,
                        )
                    except Exception:
                        raise _IssuerError("admission_consumed_marker_invalid") from None
                    if (
                        type(marker) is not dict
                        or set(marker)
                        != {
                            "schema",
                            "profile_id",
                            "case_id",
                            "admission_id",
                            "issuer_source_sha256",
                            "source_manifest_sha256",
                            "consumed_at_utc",
                        }
                        or marker["schema"] != _CONSUMED_SCHEMA
                        or marker["profile_id"] != PROFILE_ID
                        or marker["case_id"] != CASE_ID
                        or marker["admission_id"] != entry.name
                        or marker["issuer_source_sha256"] != expected_issuer
                        or marker["source_manifest_sha256"] != _SOURCE_MANIFEST_SHA256
                        or type(marker["consumed_at_utc"]) is not str
                        or not _ADMISSION_TIME_RE.fullmatch(marker["consumed_at_utc"])
                    ):
                        raise _IssuerError("admission_consumed_marker_invalid")
                else:
                    raise _IssuerError("admission_namespace_invalid")
            if len(pending) != 1:
                raise _IssuerError(
                    "admission_unavailable" if not pending else "admission_ambiguous"
                )
            stage = "admission_read_parse"
            admission_dir, _admission_dir_handle = pending[0]
            admission_path = private._path(admission_dir / "admission.json")
            admission_context = r3_cli._locked_readonly_file(admission_path, private, api)
            admission_handle, admission_identity = stack.enter_context(admission_context)
            api.verify_acl(admission_handle, sid, directory=False)
            raw_admission = r3_cli._read_bounded_handle(api, admission_handle, _ADMISSION_MAX_BYTES)
            admission = _parse_profile_admission(
                raw_admission,
                expected_bindings=expected_bindings,
            )
            if admission.admission_id != admission_dir.name:
                raise _IssuerError("admission_namespace_binding_mismatch")

            # A fixed CREATE_NEW profile claim prevents simultaneous use of
            # two separately prepared registration folders. It is persistent:
            # any failure after claiming requires a new source generation.
            stage = "profile_claim_create"
            claim_dir = private.create_private_directory(collection_dir / _ADMISSION_CLAIM_NAME)
            claim_path = private._path(claim_dir.path)
            claim_handle = stack.enter_context(_open_admission_directory(api, claim_path))
            api.verify_acl(claim_handle, sid, directory=True)
            claim_bytes = _claim_document(admission, issuer_digest)
            claim_dir.write_bytes("claim.json", claim_bytes)
            claim_file = private._path(claim_path / "claim.json")
            claim_file_handle, claim_file_identity = stack.enter_context(
                r3_cli._locked_readonly_file(claim_file, private, api)
            )
            api.verify_acl(claim_file_handle, sid, directory=False)
            if r3_cli._read_bounded_handle(api, claim_file_handle, 4096) != claim_bytes:
                raise _IssuerError("admission_claim_marker_invalid")

            stage = "consumed_marker_create"
            consumed_dir = private.create_private_directory(admission_dir / "consumed")
            consumed_path = private._path(consumed_dir.path)
            consumed_handle = stack.enter_context(_open_admission_directory(api, consumed_path))
            api.verify_acl(consumed_handle, sid, directory=True)
            marker_bytes = _consumed_document(admission, issuer_digest)
            consumed_dir.write_bytes("consumed.json", marker_bytes)
            marker_path = private._path(consumed_path / "consumed.json")
            marker_handle, marker_identity = stack.enter_context(
                r3_cli._locked_readonly_file(marker_path, private, api)
            )
            api.verify_acl(marker_handle, sid, directory=False)
            if r3_cli._read_bounded_handle(api, marker_handle, 4096) != marker_bytes:
                raise _IssuerError("admission_consumed_marker_invalid")
            admission = _C01V19Admission(
                admission_id=admission.admission_id,
                not_before_utc=admission.not_before_utc,
                expires_at_utc=admission.expires_at_utc,
                bindings=admission.bindings,
                configured_front_pair_count=admission.configured_front_pair_count,
                admission_sha256=admission.admission_sha256,
                claim_sha256=hashlib.sha256(claim_bytes).hexdigest(),
                consumed_sha256=hashlib.sha256(marker_bytes).hexdigest(),
            )
            stage = "admitted_profile_body"
            yield admission

            stage = "lease_revalidation"
            if not admission.active():
                raise _IssuerError("admission_expired_during_run")
            if (
                r3_cli._locked_file_identity(api, admission_handle, private)
                != admission_identity
            ):
                raise _IssuerError("admission_source_changed")
            api.verify_acl(admission_handle, sid, directory=False)
            if not _rewind_locked_read_handle(private, api, admission_handle):
                raise _IssuerError("admission_source_changed")
            if (
                r3_cli._read_bounded_handle(api, admission_handle, _ADMISSION_MAX_BYTES)
                != raw_admission
            ):
                raise _IssuerError("admission_source_changed")
            if r3_cli._locked_file_identity(api, marker_handle, private) != marker_identity:
                raise _IssuerError("admission_consumed_marker_changed")
            api.verify_acl(marker_handle, sid, directory=False)
            if not _rewind_locked_read_handle(private, api, marker_handle):
                raise _IssuerError("admission_consumed_marker_changed")
            if r3_cli._read_bounded_handle(api, marker_handle, 4096) != marker_bytes:
                raise _IssuerError("admission_consumed_marker_changed")
            if (
                r3_cli._locked_file_identity(api, claim_file_handle, private)
                != claim_file_identity
            ):
                raise _IssuerError("admission_claim_marker_changed")
            api.verify_acl(claim_file_handle, sid, directory=False)
            if not _rewind_locked_read_handle(private, api, claim_file_handle):
                raise _IssuerError("admission_claim_marker_changed")
            if r3_cli._read_bounded_handle(api, claim_file_handle, 4096) != claim_bytes:
                raise _IssuerError("admission_claim_marker_changed")
            if {
                item.name
                for item in _bounded_namespace_children(
                    admission_dir,
                    maximum=2,
                    reason="admission_namespace_changed",
                )
            } != {
                "admission.json",
                "consumed",
            } or {
                item.name
                for item in _bounded_namespace_children(
                    consumed_path,
                    maximum=1,
                    reason="admission_namespace_changed",
                )
            } != {
                "consumed.json"
            }:
                raise _IssuerError("admission_namespace_changed")
            if {
                item.name
                for item in _bounded_namespace_children(
                    claim_path,
                    maximum=1,
                    reason="admission_claim_namespace_changed",
                )
            } != {"claim.json"}:
                raise _IssuerError("admission_claim_namespace_changed")
    except _IssuerError:
        raise
    except Exception as error:
        raise _AdmissionLeaseFailure(stage, _admission_failure_class(error)) from None
    finally:
        close_failure_class = None
        try:
            source_stack.close()
        except Exception as error:
            close_failure_class = _admission_failure_class(error)
        for module in modules:
            if sys.modules.get(module.__name__) is module:
                sys.modules.pop(module.__name__, None)
        if close_failure_class is not None:
            raise _AdmissionLeaseFailure(
                "source_handle_close",
                close_failure_class,
                reason="admission_source_handle_close_failed",
            ) from None


def _parse_private_config(raw: bytes, selector: Any) -> Tuple[dict[str, str], ...]:
    if type(raw) is not bytes or not 0 < len(raw) <= MAX_CONFIG_BYTES:
        raise _IssuerError("private_config_size_invalid")
    try:
        text = raw.decode("ascii")
        value = json.loads(
            text,
            object_pairs_hook=_strict_object,
            parse_constant=lambda _item: (_ for _ in ()).throw(
                _IssuerError("private_config_nonfinite_number")
            ),
        )
    except _IssuerError:
        raise
    except Exception:
        raise _IssuerError("private_config_invalid") from None
    if type(value) is not dict or set(value) != {
        "config_schema_version",
        "strategy",
        "runtime",
        "parameters",
        "secrets_ref",
        "ctp",
    }:
        raise _IssuerError("private_config_schema_invalid")
    if (
        type(value["config_schema_version"]) is not int
        or value["config_schema_version"] != 4
        or value["strategy"] != {"id": "example.000_live_certification.simnow_penetration"}
        or value["runtime"] != {"mode": "simulation", "preset": "sandbox"}
        or value["parameters"] != {}
        or value["secrets_ref"] != "config_yaml"
    ):
        raise _IssuerError("private_config_scope_invalid")
    try:
        canonical = (
            json.dumps(
                value,
                ensure_ascii=True,
                allow_nan=False,
                sort_keys=True,
                separators=(",", ":"),
            )
            + "\n"
        ).encode("ascii")
    except Exception:
        raise _IssuerError("private_config_not_canonical") from None
    if canonical != raw:
        raise _IssuerError("private_config_not_canonical")
    ctp = value["ctp"]
    if type(ctp) is not dict or set(ctp) != {
        "front_pairs",
        "instrument_id",
        "exchange_id",
        "hedge_flag",
        "broker_id",
        "user_id",
        "password",
        "app_id",
        "auth_code",
    }:
        raise _IssuerError("private_config_ctp_shape_invalid")
    pairs = ctp["front_pairs"]
    if type(pairs) is not list or not 1 <= len(pairs) <= 8:
        raise _IssuerError("configured_front_pair_count_invalid")
    normalized: List[dict[str, str]] = []
    for pair in pairs:
        if (
            type(pair) is not dict
            or set(pair) != {"md_front", "td_front"}
            or type(pair.get("md_front")) is not str
            or type(pair.get("td_front")) is not str
            or not pair["md_front"].isascii()
            or not pair["td_front"].isascii()
        ):
            raise _IssuerError("configured_front_pair_invalid")
        normalized.append({"md_front": pair["md_front"], "td_front": pair["td_front"]})
    try:
        selector.validate_document(
            {
                "schema": selector.SCHEMA,
                "venue": "simnow",
                "scope": "transport_only",
                "strategy_id": selector.STRATEGY,
                "front_pairs": normalized,
            }
        )
    except Exception:
        raise _IssuerError("configured_front_pair_invalid") from None
    return tuple(normalized)


def _require_clean_ambient_secrets() -> None:
    """Require the root's UNSET launcher before any private config/env reads."""

    if any(name in os.environ for name in _AMBIENT_SECRET_AND_FRONT_NAMES):
        raise _IssuerError("ambient_secret_environment_present")


def _require_ignored_untracked_config(root: Path, helpers: Mapping[str, Any]) -> None:
    private = helpers["private"]
    r3_cli = helpers["r3_cli"]
    try:
        git = r3_cli._git_executable(private)
        relative = _CONFIG_RELATIVE.replace("/", os.sep)
        environment = {
            key: os.environ[key]
            for key in ("SYSTEMROOT", "WINDIR", "PATH", "TEMP", "TMP")
            if key in os.environ
        }
        environment.update(
            GIT_CONFIG_NOSYSTEM="1",
            GIT_CONFIG_GLOBAL=os.devnull,
            GIT_CONFIG_COUNT="2",
            GIT_CONFIG_KEY_0="core.fsmonitor",
            GIT_CONFIG_VALUE_0="false",
            GIT_CONFIG_KEY_1="core.excludesFile",
            GIT_CONFIG_VALUE_1=os.devnull,
            GIT_OPTIONAL_LOCKS="0",
            GIT_TERMINAL_PROMPT="0",
        )
        common = {
            "cwd": str(root),
            "env": environment,
            "stdin": subprocess.DEVNULL,
            "stdout": subprocess.DEVNULL,
            "stderr": subprocess.DEVNULL,
            "timeout": 10,
            "check": False,
        }
        ignored = subprocess.run(
            [str(git), "-C", str(root), "check-ignore", "--quiet", "--", relative],
            **common,
        )
        tracked = subprocess.run(
            [
                str(git),
                "-C",
                str(root),
                "ls-files",
                "--error-unmatch",
                "--",
                relative,
            ],
            **common,
        )
    except Exception:
        raise _IssuerError("private_config_ignore_check_failed") from None
    if ignored.returncode != 0 or tracked.returncode != 1:
        raise _IssuerError("private_config_not_ignored_untracked")


def _private_pair_config_lease(root: Path, helpers: Mapping[str, Any]) -> Any:
    """Retain read-only identity/ACL custody of the ignored suite config."""

    from contextlib import contextmanager

    @contextmanager
    def lease():
        private = helpers["private"]
        r3_cli = helpers["r3_cli"]
        path = root / Path(_CONFIG_RELATIVE)
        _require_ignored_untracked_config(root, helpers)
        stack = ExitStack()

        def close_preserving_exception() -> None:
            try:
                stack.close()
            except BaseException:
                pass

        try:
            info = path.lstat()
            if (
                path.is_symlink()
                or getattr(info, "st_file_attributes", 0) & 0x400
                or not path.is_file()
                or not path.is_absolute()
            ):
                raise _IssuerError("private_config_file_invalid")
            api = private._api()
            sid = api.current_sid()
            stack.enter_context(r3_cli._credential_ancestor_locks(path, private))
            handle, identity = stack.enter_context(r3_cli._locked_readonly_file(path, private, api))
            api.verify_acl(handle, sid, directory=False)
            raw = r3_cli._read_bounded_handle(api, handle, MAX_CONFIG_BYTES)
            front_pairs = _parse_private_config(raw, helpers["selector"])
            config_digest = hashlib.sha256(raw).hexdigest()

            def verify_current() -> None:
                api.verify_acl(handle, sid, directory=False)
                with r3_cli._locked_readonly_file(path, private, api) as (
                    other,
                    other_identity,
                ):
                    if other_identity != identity:
                        raise _IssuerError("private_config_identity_changed")
                    api.verify_acl(other, sid, directory=False)
                    current = r3_cli._read_bounded_handle(api, other, MAX_CONFIG_BYTES)
                if hashlib.sha256(current).hexdigest() != config_digest:
                    raise _IssuerError("private_config_changed_during_run")
                if _parse_private_config(current, helpers["selector"]) != front_pairs:
                    raise _IssuerError("private_config_pair_set_changed")

        except _IssuerError:
            close_preserving_exception()
            raise
        except Exception:
            close_preserving_exception()
            raise _IssuerError("private_config_unavailable") from None
        except BaseException:
            close_preserving_exception()
            raise

        try:
            yield front_pairs, config_digest, verify_current
        except BaseException:
            close_preserving_exception()
            raise

        try:
            verify_current()
        except _IssuerError:
            close_preserving_exception()
            raise
        except Exception:
            close_preserving_exception()
            raise _IssuerError("private_config_unavailable") from None
        except BaseException:
            close_preserving_exception()
            raise
        try:
            stack.close()
        except Exception:
            raise _IssuerError("private_config_unavailable") from None

    return lease()


def _credential_lease(
    owner: ModuleType,
    root: Path,
    helpers: Mapping[str, Any],
    front_pairs: Sequence[Mapping[str, str]],
    pair_binding: Any,
    *,
    expected_projection_sha256: str,
) -> Any:
    """Resolve only the five config-first EnvRefs under retained .env custody."""

    from contextlib import contextmanager

    @contextmanager
    def lease():
        selected_pair = _selected_pair_from_binding(
            helpers,
            front_pairs,
            pair_binding,
            expected_projection_sha256=expected_projection_sha256,
        )
        private = helpers["private"]
        r3_cli = helpers["r3_cli"]
        renderer = helpers["renderer"]
        env_path = root / ".env"
        api = private._api()
        stack = ExitStack()

        def close_preserving_exception() -> None:
            try:
                stack.close()
            except BaseException:
                pass

        try:
            stack.enter_context(r3_cli._require_ignored_env(env_path, private))
            stack.enter_context(r3_cli._credential_ancestor_locks(env_path, private))
            handle, _identity = stack.enter_context(
                r3_cli._locked_readonly_file(env_path, private, api)
            )
            api.verify_acl(handle, api.current_sid(), directory=False)
            raw = r3_cli._read_bounded_handle(api, handle, renderer.MAX_ENV_FILE_BYTES)
            values = renderer._parse_env_file(raw, _ENV_NAMES)
            fields = {}
            for field, name in _FIELD_ENV_NAMES.items():
                value = owner._validate_text(values[name], _ENV_VALUE_MAX_BYTES[field])
                fields[field] = value
            credentials = owner._Credentials(
                broker_id=fields["broker_id"],
                user_id=fields["user_id"],
                password=fields["password"],
                app_id=fields["app_id"],
                auth_code=fields["auth_code"],
                product_info=owner._PRODUCT_INFO,
                md_front=selected_pair["md_front"],
                td_front=selected_pair["td_front"],
            )
        except _IssuerError:
            close_preserving_exception()
            raise
        except Exception:
            close_preserving_exception()
            raise _IssuerError("explicit_credential_source_unavailable") from None
        except BaseException:
            close_preserving_exception()
            raise

        try:
            yield credentials
        except BaseException:
            close_preserving_exception()
            raise

        try:
            api.verify_acl(handle, api.current_sid(), directory=False)
        except _IssuerError:
            close_preserving_exception()
            raise
        except Exception:
            close_preserving_exception()
            raise _IssuerError("explicit_credential_source_unavailable") from None
        except BaseException:
            close_preserving_exception()
            raise
        try:
            stack.close()
        except Exception:
            raise _IssuerError("explicit_credential_source_unavailable") from None

    return lease()


def _pair_projection(helpers: Mapping[str, Any], front_pairs: Sequence[Mapping[str, str]]) -> bytes:
    selector = helpers["selector"]
    if type(front_pairs) not in (tuple, list) or not 1 <= len(front_pairs) <= 8:
        raise _IssuerError("configured_front_pair_count_invalid")
    normalized = []
    for pair in front_pairs:
        if (
            not isinstance(pair, Mapping)
            or set(pair) != {"md_front", "td_front"}
            or type(pair.get("md_front")) is not str
            or type(pair.get("td_front")) is not str
        ):
            raise _IssuerError("configured_front_pair_invalid")
        normalized.append({"md_front": pair["md_front"], "td_front": pair["td_front"]})
    document = {
        "schema": selector.SCHEMA,
        "venue": "simnow",
        "scope": "transport_only",
        "strategy_id": selector.STRATEGY,
        "front_pairs": normalized,
    }
    try:
        raw = json.dumps(
            document,
            ensure_ascii=True,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("ascii")
        if not 0 < len(raw) <= MAX_PROJECTION_BYTES:
            raise ValueError("size")
        selector.parse_document(raw)
    except Exception:
        raise _IssuerError("configured_front_projection_invalid") from None
    return raw


def _selected_pair_from_binding(
    helpers: Mapping[str, Any],
    front_pairs: Sequence[Mapping[str, str]],
    pair_binding: Any,
    *,
    expected_projection_sha256: str,
) -> dict[str, str]:
    """Bind the selected credential fronts to the current complete projection."""

    protocol = helpers["protocol"]
    try:
        projection = _pair_projection(helpers, front_pairs)
        if (
            type(expected_projection_sha256) is not str
            or not _SHA256_RE.fullmatch(expected_projection_sha256)
            or hashlib.sha256(projection).hexdigest() != expected_projection_sha256
            or type(pair_binding) is not protocol.C01PairBinding
            or type(pair_binding.selected_index) is not int
            or not 0 <= pair_binding.selected_index < len(front_pairs)
            or type(pair_binding.selection_sha256) is not str
            or not _SHA256_RE.fullmatch(pair_binding.selection_sha256)
            or type(pair_binding.md_front_sha256) is not str
            or not _SHA256_RE.fullmatch(pair_binding.md_front_sha256)
            or type(pair_binding.td_front_sha256) is not str
            or not _SHA256_RE.fullmatch(pair_binding.td_front_sha256)
            or type(pair_binding.td_front) is not str
        ):
            raise ValueError("pair_binding")
        selected = front_pairs[pair_binding.selected_index]
        if (
            type(selected) not in (dict, MappingProxyType)
            or set(selected) != {"md_front", "td_front"}
            or type(selected["md_front"]) is not str
            or type(selected["td_front"]) is not str
            or pair_binding.md_front_sha256
            != hashlib.sha256(selected["md_front"].encode("utf-8")).hexdigest()
            or pair_binding.td_front_sha256
            != hashlib.sha256(selected["td_front"].encode("utf-8")).hexdigest()
            or pair_binding.td_front != selected["td_front"]
        ):
            raise ValueError("selected_pair")
        return {"md_front": selected["md_front"], "td_front": selected["td_front"]}
    except _IssuerError:
        raise
    except Exception:
        raise _IssuerError("fresh_pair_binding_invalid") from None


def _fresh_pair_selection_value(
    degraded_candidate: Any, observation_binding_sha256: Any
) -> dict[str, Any]:
    if (
        type(degraded_candidate) is not bool
        or type(observation_binding_sha256) is not str
        or not _SHA256_RE.fullmatch(observation_binding_sha256)
    ):
        raise _IssuerError("fresh_pair_binding_invalid")
    return {
        "source": _FRESH_PAIR_SELECTION_SOURCE,
        "degraded_candidate": degraded_candidate,
        "observation_binding_sha256": observation_binding_sha256,
    }


def _validate_fresh_pair_selection(
    value: Any, *, expected_selection_sha256: Any = None
) -> dict[str, Any] | None:
    if value is None:
        return None
    if (
        type(value) is not dict
        or set(value) != {"source", "degraded_candidate", "observation_binding_sha256"}
        or value.get("source") != _FRESH_PAIR_SELECTION_SOURCE
        or type(value.get("degraded_candidate")) is not bool
        or type(value.get("observation_binding_sha256")) is not str
        or not _SHA256_RE.fullmatch(value["observation_binding_sha256"])
    ):
        raise _IssuerError("fresh_pair_binding_invalid")
    if expected_selection_sha256 is not None and (
        type(expected_selection_sha256) is not str
        or not _SHA256_RE.fullmatch(expected_selection_sha256)
        or value["observation_binding_sha256"] != expected_selection_sha256
    ):
        raise _IssuerError("fresh_pair_binding_invalid")
    return {
        "source": _FRESH_PAIR_SELECTION_SOURCE,
        "degraded_candidate": value["degraded_candidate"],
        "observation_binding_sha256": value["observation_binding_sha256"],
    }


def _select_current_pair(
    helpers: Mapping[str, Any],
    front_pairs: Sequence[Mapping[str, str]],
    *,
    deadline: float,
    audit_sink: dict[str, Any] | None = None,
    connector: Any = None,
    probe_clock: Any = None,
) -> Any:
    if time.monotonic() >= deadline:
        raise _IssuerError("issuer_deadline_exceeded")
    if audit_sink is not None and (
        type(audit_sink) is not dict or "fresh_pair_selection" in audit_sink
    ):
        raise _IssuerError("fresh_pair_binding_invalid")
    handoff_module = helpers["handoff"]
    protocol = helpers["protocol"]
    projection = _pair_projection(helpers, front_pairs)
    try:
        handoff = handoff_module.create_current_handoff(
            projection,
            confirm_transport_only=True,
            connector=connector,
            probe_clock=probe_clock,
        )
        selected = handoff.consume(projection)
    except Exception as error:
        handoff_error_type = getattr(handoff_module, "FrontHandoffError", None)
        code = None
        if type(error) is handoff_error_type:
            args = error.args
            if type(args) is tuple and len(args) == 1 and type(args[0]) is str:
                code = args[0]
        reason = _FRESH_PAIR_HANDOFF_FAILURES.get(code, "fresh_pair_local_failure")
        raise _IssuerError(reason) from None
    selection_type = getattr(handoff_module, "SelectedFrontPair", None)
    if (
        type(selected) is not selection_type
        or type(selected.config_index) is not int
        or not 0 <= selected.config_index < len(front_pairs)
        or selected.execution_authority != "NONE"
        or type(selected.degraded_candidate) is not bool
        or selected.public_projection_sha256 != hashlib.sha256(projection).hexdigest()
        or (selected.md_front, selected.td_front)
        != (
            front_pairs[selected.config_index]["md_front"],
            front_pairs[selected.config_index]["td_front"],
        )
        or time.monotonic() >= deadline
    ):
        raise _IssuerError("fresh_pair_binding_invalid")
    try:
        binding = protocol.C01PairBinding(
            selected_index=selected.config_index,
            selection_sha256=selected.observation_sha256,
            md_front_sha256=hashlib.sha256(selected.md_front.encode("utf-8")).hexdigest(),
            td_front_sha256=hashlib.sha256(selected.td_front.encode("utf-8")).hexdigest(),
            td_front=selected.td_front,
            selected_at_utc=helpers["owner_now_utc"](),
        )
    except Exception:
        raise _IssuerError("fresh_pair_binding_invalid") from None
    if (
        type(binding) is not protocol.C01PairBinding
        or binding.selection_sha256 != selected.observation_sha256
    ):
        raise _IssuerError("fresh_pair_binding_invalid")
    if audit_sink is not None:
        audit_sink["fresh_pair_selection"] = _validate_fresh_pair_selection(
            _fresh_pair_selection_value(selected.degraded_candidate, selected.observation_sha256),
            expected_selection_sha256=binding.selection_sha256,
        )
    return binding


def _validation_issues_pass(contract: Any, protocol: Any, validation: Any) -> bool:
    return (
        type(validation) is protocol.C01CandidateValidation
        and validation.status == "BLOCKED"
        and validation.eligible_for_protected_admission is True
        and validation.reasons == (contract._PROTECTED_ADMISSION_REQUIRED,)
        and validation.checked_request_count == 8
        and validation.checked_query_callback_count >= 6
        and validation.checked_snapshot_count == 2
    )


def _canonical_digest(value: Any) -> str:
    raw = json.dumps(
        value,
        ensure_ascii=True,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("ascii")
    return hashlib.sha256(raw).hexdigest()


_WORKER_PROGRESS_STAGE_EVENTS = {
    "worker": frozenset({"begin"}),
    "private_paths": frozenset({"end"}),
    "sdk_install_verify": frozenset({"begin", "end"}),
    "sdk_import": frozenset({"begin", "end"}),
    "client_construct": frozenset({"begin", "end"}),
    "client_start": frozenset({"begin", "end"}),
    "client_no_join_start_policy": frozenset({"begin", "end", "failed"}),
    "client_start_native_module_check": frozenset({"begin", "end", "failed"}),
    "client_start_generation_reserve": frozenset({"begin", "end", "failed"}),
    "client_start_identity_validate": frozenset({"begin", "end", "failed"}),
    "client_start_identity_compare": frozenset({"begin", "end", "failed"}),
    "client_start_flow_prepare": frozenset({"begin", "end", "failed"}),
    "native_create_trader_api": frozenset({"begin", "end", "failed"}),
    "native_register_spi_attach": frozenset({"begin", "end", "failed"}),
    "native_subscribe_private_topic": frozenset({"begin", "end", "failed"}),
    "native_subscribe_public_topic": frozenset({"begin", "end", "failed"}),
    "native_register_front": frozenset({"begin", "end", "failed"}),
    "native_api_init": frozenset({"begin", "end", "failed"}),
    "native_register_spi_detach": frozenset({"begin", "end", "failed"}),
    "native_release": frozenset({"begin", "end", "failed"}),
    "login_wait": frozenset({"begin", "end"}),
    "snapshot_directory": frozenset({"begin", "end"}),
    "authenticate_request": frozenset({"begin", "end"}),
    "login_request": frozenset({"begin", "end"}),
    "authenticate_callback": frozenset({"callback_first", "callback_terminal"}),
    "login_callback": frozenset({"callback_first", "callback_terminal"}),
    "baseline_orders_request": frozenset({"begin", "end"}),
    "baseline_positions_request": frozenset({"begin", "end"}),
    "baseline_funds_request": frozenset({"begin", "end"}),
    "final_orders_request": frozenset({"begin", "end"}),
    "final_positions_request": frozenset({"begin", "end"}),
    "final_funds_request": frozenset({"begin", "end"}),
    "baseline_orders_callback": frozenset({"callback_first", "callback_terminal"}),
    "baseline_positions_callback": frozenset({"callback_first", "callback_terminal"}),
    "baseline_funds_callback": frozenset({"callback_first", "callback_terminal"}),
    "final_orders_callback": frozenset({"callback_first", "callback_terminal"}),
    "final_positions_callback": frozenset({"callback_first", "callback_terminal"}),
    "final_funds_callback": frozenset({"callback_first", "callback_terminal"}),
    "baseline_orders_read": frozenset({"begin", "end"}),
    "baseline_positions_read": frozenset({"begin", "end"}),
    "baseline_funds_read": frozenset({"begin", "end"}),
    "final_orders_read": frozenset({"begin", "end"}),
    "final_positions_read": frozenset({"begin", "end"}),
    "final_funds_read": frozenset({"begin", "end"}),
    "baseline_snapshot_write": frozenset({"begin", "end"}),
    "final_snapshot_write": frozenset({"begin", "end"}),
    "native_stop": frozenset({"begin", "end", "failed"}),
    "worker_receipt": frozenset({"begin", "end"}),
}
_WORKER_PROGRESS_KEYS = frozenset(
    {
        "protocol",
        "version",
        "case_id",
        "sequence",
        "stage",
        "event",
        "run_nonce",
        "parent_pid",
        "worker_pid",
        "worker_source_sha256",
        "account_scope_sha256",
        "credential_binding_sha256",
        "pair_binding",
        "recorded_at_utc",
        "recorded_monotonic_ns",
        "previous_record_sha256",
    }
)
_WORKER_PROGRESS_FILENAME_RE = re.compile(r"progress-([0-9]{3})\.json\Z")
_WORKER_PROGRESS_UTC_RE = re.compile(
    r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}\.[0-9]{6}Z\Z"
)


def _progress_summary(
    payloads: Mapping[str, bytes],
    *,
    run_nonce: Any,
    parent_pid: Any,
    worker_pid: Any,
    worker_source_sha256: Any,
    pair_binding: Any,
    account_scope_sha256: Any,
    credential_binding_sha256: Any,
) -> dict[str, Any]:
    """Verify a bounded local progress prefix and return only safe stage facts."""

    safe_records: list[dict[str, Any]] = []

    def result(status: str) -> dict[str, Any]:
        last = safe_records[-1] if safe_records else None
        return {
            "schema": "simnow.c01.native-progress-summary.v1",
            "status": status,
            "record_count": len(safe_records),
            "records": safe_records,
            "last_stage": last["stage"] if last else None,
            "last_event": last["event"] if last else None,
            "last_recorded_at_utc": last["recorded_at_utc"] if last else None,
            "last_recorded_monotonic_ns": last["recorded_monotonic_ns"] if last else None,
            "worker_pid": last["worker_pid"] if last else worker_pid,
        }

    if type(payloads) is not dict or not payloads:
        return result("missing")
    if (
        len(payloads) > MAX_WORKER_PROGRESS_RECORDS
        or type(run_nonce) is not str
        or not re.fullmatch(r"[0-9a-f]{32}", run_nonce)
        or type(parent_pid) is not int
        or parent_pid < 1
        or type(worker_pid) is not int
        or worker_pid < 1
        or type(worker_source_sha256) is not str
        or not _SHA256_RE.fullmatch(worker_source_sha256)
        or type(account_scope_sha256) is not str
        or not _SHA256_RE.fullmatch(account_scope_sha256)
        or type(credential_binding_sha256) is not str
        or not _SHA256_RE.fullmatch(credential_binding_sha256)
        or type(pair_binding) is not dict
    ):
        return result("invalid")
    filenames = sorted(payloads)
    expected_names = [
        "progress-{:03d}.json".format(index) for index in range(1, len(filenames) + 1)
    ]
    if filenames != expected_names:
        return result("invalid")
    total_bytes = 0
    previous_sha256 = "0" * 64
    seen_events: dict[str, set[str]] = {}
    complete_marker = False
    for index, filename in enumerate(filenames, start=1):
        raw = payloads[filename]
        if type(raw) is not bytes:
            return result("invalid")
        total_bytes += len(raw)
        if (
            len(raw) > MAX_WORKER_PROGRESS_RECORD_BYTES
            or total_bytes > MAX_WORKER_PROGRESS_TOTAL_BYTES
            or not raw.endswith(b"\n")
            or complete_marker
        ):
            return result("invalid")
        try:
            document = json.loads(raw.decode("ascii"))
            canonical = (
                json.dumps(
                    document,
                    ensure_ascii=True,
                    allow_nan=False,
                    sort_keys=True,
                    separators=(",", ":"),
                ).encode("ascii")
                + b"\n"
            )
        except Exception:
            return result("invalid")
        if type(document) is not dict or set(document) != _WORKER_PROGRESS_KEYS or raw != canonical:
            return result("invalid")
        stage = document.get("stage")
        event = document.get("event")
        if (
            document.get("protocol") != "simnow.c01.native-progress.v1"
            or type(document.get("version")) is not int
            or document["version"] != 1
            or document.get("case_id") != "C01"
            or type(document.get("sequence")) is not int
            or document["sequence"] != index
            or type(stage) is not str
            or stage not in _WORKER_PROGRESS_STAGE_EVENTS
            or type(event) is not str
            or event not in _WORKER_PROGRESS_STAGE_EVENTS[stage]
            or document.get("run_nonce") != run_nonce
            or type(document.get("parent_pid")) is not int
            or document["parent_pid"] != parent_pid
            or type(document.get("worker_pid")) is not int
            or document["worker_pid"] != worker_pid
            or document.get("worker_source_sha256") != worker_source_sha256
            or document.get("account_scope_sha256") != account_scope_sha256
            or document.get("credential_binding_sha256") != credential_binding_sha256
            or document.get("pair_binding") != pair_binding
            or type(document.get("recorded_at_utc")) is not str
            or not _WORKER_PROGRESS_UTC_RE.fullmatch(document["recorded_at_utc"])
            or type(document.get("recorded_monotonic_ns")) is not int
            or document["recorded_monotonic_ns"] < 1
            or document.get("previous_record_sha256") != previous_sha256
        ):
            return result("invalid")
        stage_seen = seen_events.setdefault(stage, set())
        if event in stage_seen:
            return result("invalid")
        if event == "end" and stage not in {"private_paths"} and "begin" not in stage_seen:
            return result("invalid")
        if event == "failed" and "begin" not in stage_seen:
            return result("invalid")
        if event == "callback_terminal" and "callback_first" not in stage_seen:
            return result("invalid")
        stage_seen.add(event)
        safe_records.append(
            {
                "sequence": index,
                "stage": stage,
                "event": event,
                "recorded_at_utc": document["recorded_at_utc"],
                "recorded_monotonic_ns": document["recorded_monotonic_ns"],
                "worker_pid": document["worker_pid"],
            }
        )
        previous_sha256 = hashlib.sha256(raw).hexdigest()
        complete_marker = stage == "worker_receipt" and event == "end"
    return result("verified")


def _empty_progress_summary(status: str, worker_pid: Any = None) -> dict[str, Any]:
    if status not in {"missing", "invalid", "unavailable"}:
        status = "unavailable"
    return {
        "schema": "simnow.c01.native-progress-summary.v1",
        "status": status,
        "record_count": 0,
        "records": [],
        "last_stage": None,
        "last_event": None,
        "last_recorded_at_utc": None,
        "last_recorded_monotonic_ns": None,
        "worker_pid": worker_pid if type(worker_pid) is int and worker_pid > 0 else None,
    }


_WORKER_PROGRESS_SUMMARY_KEYS = frozenset(
    {
        "schema",
        "status",
        "record_count",
        "records",
        "last_stage",
        "last_event",
        "last_recorded_at_utc",
        "last_recorded_monotonic_ns",
        "worker_pid",
    }
)
_WORKER_PROGRESS_RECORD_SUMMARY_KEYS = frozenset(
    {"sequence", "stage", "event", "recorded_at_utc", "recorded_monotonic_ns", "worker_pid"}
)


def _safe_progress_summary(value: Any) -> dict[str, Any]:
    """Keep only the public-safe fixed progress summary fields for the audit."""

    if type(value) is not dict or set(value) != _WORKER_PROGRESS_SUMMARY_KEYS:
        return _empty_progress_summary("unavailable")
    status = value.get("status")
    records = value.get("records")
    if (
        value.get("schema") != "simnow.c01.native-progress-summary.v1"
        or status not in {"missing", "invalid", "unavailable", "verified"}
        or type(value.get("record_count")) is not int
        or not 0 <= value["record_count"] <= MAX_WORKER_PROGRESS_RECORDS
        or type(records) is not list
        or len(records) != value["record_count"]
    ):
        return _empty_progress_summary("unavailable")
    safe_records = []
    for index, item in enumerate(records, start=1):
        if (
            type(item) is not dict
            or set(item) != _WORKER_PROGRESS_RECORD_SUMMARY_KEYS
            or type(item.get("sequence")) is not int
            or item["sequence"] != index
            or type(item.get("stage")) is not str
            or item["stage"] not in _WORKER_PROGRESS_STAGE_EVENTS
            or type(item.get("event")) is not str
            or item["event"] not in _WORKER_PROGRESS_STAGE_EVENTS[item["stage"]]
            or type(item.get("recorded_at_utc")) is not str
            or not _WORKER_PROGRESS_UTC_RE.fullmatch(item["recorded_at_utc"])
            or type(item.get("recorded_monotonic_ns")) is not int
            or item["recorded_monotonic_ns"] < 1
            or type(item.get("worker_pid")) is not int
            or item["worker_pid"] < 1
        ):
            return _empty_progress_summary("unavailable")
        safe_records.append(dict(item))
    last = safe_records[-1] if safe_records else None
    expected_last = {
        "last_stage": last["stage"] if last else None,
        "last_event": last["event"] if last else None,
        "last_recorded_at_utc": last["recorded_at_utc"] if last else None,
        "last_recorded_monotonic_ns": last["recorded_monotonic_ns"] if last else None,
        "worker_pid": last["worker_pid"] if last else value.get("worker_pid"),
    }
    if any(value.get(key) != expected for key, expected in expected_last.items()):
        return _empty_progress_summary("unavailable")
    if status == "verified" and not safe_records:
        return _empty_progress_summary("unavailable")
    if status in {"missing", "unavailable"} and safe_records:
        return _empty_progress_summary("unavailable")
    return {
        "schema": "simnow.c01.native-progress-summary.v1",
        "status": status,
        "record_count": len(safe_records),
        "records": safe_records,
        **expected_last,
    }


_WORKER_OBSERVATION_SCHEMA = "simnow.c01.worker-observation.v2"
_WORKER_FAILURE_DIAGNOSTIC_SCHEMA = "simnow.c01.worker-failure-diagnostic.v1"
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
        "worker_frame_invalid",
        "worker_frame_misbinding",
        "worker_job_accounting_unknown",
        "worker_process_incomplete",
        "worker_result_invalid",
        "worker_setup_failed",
        "worker_source_unavailable",
        "worker_stderr_unexpected",
        "worker_stdin_incomplete",
    }
)
_WORKER_OBSERVATION_PROGRESS_STATUSES = frozenset(
    {"verified", "missing", "invalid", "unavailable", "UNOBSERVED"}
)
_WORKER_OBSERVATION_EVENT_NAMES = frozenset(
    {"begin", "end", "failed", "callback_first", "callback_terminal"}
)
_WORKER_OBSERVATION_SUPERVISOR_TYPES = frozenset(
    {"expected", "unexpected", "unobserved"}
)
_WORKER_OBSERVATION_LIFECYCLE_TYPES = frozenset(
    {"expected", "unexpected", "unobserved"}
)
_WORKER_OBSERVATION_RECEIPT_TYPES = frozenset(
    {"expected", "none", "invalid", "unexpected", "unobserved"}
)
_FAILURE_DIAGNOSTIC_KEYS = frozenset(
    {
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
)
_FAILURE_TOP_LEVEL_KEYS = frozenset(
    {
        "protocol",
        "case_id",
        "failure_code",
        "worker_source_sha256",
        "run_nonce",
        "parent_pid",
        "worker_pid",
        "pair_binding",
        "account_scope_sha256",
        "credential_binding_sha256",
        "client",
        "requests",
        "callbacks",
        "private_auth_login_callback_rows",
        "query_callbacks",
        "snapshots",
        "write_counters",
        "native_close",
        "native_close_error_code",
    }
)
_FAILURE_REQUEST_KEYS = frozenset(
    {
        "kind",
        "phase",
        "family",
        "method",
        "request_id",
        "request_generation",
        "local_sequence",
        "issued_at_utc",
        "issued_monotonic_ns",
        "return_code",
        "sdk_query_result",
        "receipt_origin",
        "account_scope_sha256",
        "credential_binding_sha256",
    }
)
_FAILURE_CALLBACK_KEYS = frozenset(
    {
        "kind",
        "phase",
        "family",
        "callback_name",
        "request_id",
        "error_id",
        "rsp_info_present",
        "error_semantics",
        "is_last",
        "request_generation",
        "client_instance_id",
        "client_generation",
        "arrival_generation",
        "local_sequence",
        "arrived_at_utc",
        "arrived_monotonic_ns",
        "row_present",
        "front_id",
        "session_id",
        "trading_day",
        "account_scope_sha256",
        "credential_binding_sha256",
    }
)
_FAILURE_PRIVATE_ROW_KEYS = frozenset(
    {
        "callback_name",
        "request_id",
        "request_generation",
        "local_sequence",
        "row_present",
        "row",
        "capture_error",
    }
)
_FAILURE_QUERY_FACT_KEYS = frozenset({"request_id", "phase", "family", "callbacks"})
_FAILURE_QUERY_CALLBACK_KEYS = frozenset(
    {
        "callback_name",
        "request_id",
        "error_id",
        "rsp_info_present",
        "error_semantics",
        "is_last",
        "request_generation",
        "local_sequence",
        "arrived_at_utc",
        "arrived_monotonic_ns",
        "row_present",
        "row",
    }
)
_FAILURE_SNAPSHOT_KEYS = frozenset(
    {
        "phase",
        "artifact_ref",
        "artifact_sha256",
        "client_instance_id",
        "client_generation",
        "arrival_generation",
        "session_id",
        "trading_day",
        "queries",
        "open_order_refs_sha256",
        "order_economics_sha256",
        "positions_sha256",
        "funds_sha256",
    }
)


def _unobserved_failure_diagnostic() -> dict[str, Any]:
    return {
        "schema": _WORKER_FAILURE_DIAGNOSTIC_SCHEMA,
        "status": "UNOBSERVED",
        "failure_code_ordinal": None,
        "request_count": None,
        "callback_count": None,
        "auth_login_callback_row_count": None,
        "query_request_count": None,
        "query_event_count": None,
        "baseline_query_callback_count": None,
        "final_query_callback_count": None,
        "snapshot_count": None,
        "baseline_snapshot_count": None,
        "final_snapshot_count": None,
        "order_insert_requests": None,
        "order_cancel_requests": None,
        "native_close_status": "UNOBSERVED",
        "position_text_probe": _unobserved_position_text_probe(),
    }


def _valid_json_payload(value: Any, *, depth: int = 0, budget: list[int] | None = None) -> bool:
    """Bound nested callback rows without retaining or projecting their values."""

    if budget is None:
        budget = [100000]
    budget[0] -= 1
    if budget[0] < 0 or depth > 24:
        return False
    if value is None or type(value) in (bool, int, str):
        return type(value) is not str or len(value) <= 32768
    if type(value) is float:
        return value == value and abs(value) != float("inf")
    if type(value) is list:
        return len(value) <= 10000 and all(
            _valid_json_payload(item, depth=depth + 1, budget=budget) for item in value
        )
    if type(value) is dict:
        return len(value) <= 10000 and all(
            type(key) is str
            and len(key) <= 256
            and _valid_json_payload(item, depth=depth + 1, budget=budget)
            for key, item in value.items()
        )
    return False


_POSITION_TEXT_PROBE_FIELDS = (
    ("positions", 1, "ExchangeID", False),
    ("positions", 2, "InstrumentID", False),
    ("positions", 3, "PosiDirection", False),
    ("positions", 4, "HedgeFlag", False),
    ("positions", 5, "PositionDate", False),
    ("positions", 6, "BrokerID", False),
    ("positions", 7, "InvestorID", False),
    ("positions", 8, "TradingDay", False),
    ("positions", 9, "InvestUnitID", True),
    ("positions", 10, "reserve1", True),
    ("funds", 1, "BrokerID", False),
    ("funds", 2, "AccountID", False),
    ("funds", 3, "CurrencyID", False),
    ("funds", 4, "BizType", False),
    ("funds", 5, "TradingDay", False),
)
_POSITION_TEXT_PROBE_FIELDS_BY_FAMILY = MappingProxyType(
    {
        family: tuple(item for item in _POSITION_TEXT_PROBE_FIELDS if item[0] == family)
        for family in ("positions", "funds")
    }
)
_POSITION_TEXT_PROBE_CATEGORIES = frozenset(
    {"EMPTY", "NUL_ONLY", "CONTROL", "ASCII_DECODE", "WHITESPACE", "TOO_LONG", "TYPE", "MISSING", "UNOBSERVED"}
)
_POSITION_TEXT_PROBE_TYPES = frozenset({"str", "bytes", "int", "float", "null", "other"})
_POSITION_TEXT_PROBE_SCHEMA = "simnow.c01.position_text_shape_probe.v1"
_POSITION_TEXT_PROBE_MAX_CHARS = 128  # Exact bound in the pinned V2 worker.


def _unobserved_position_text_probe() -> dict[str, Any]:
    return {
        "schema": _POSITION_TEXT_PROBE_SCHEMA,
        "family": None,
        "field_ordinal": None,
        "field": None,
        "type_bucket": None,
        "invalid_category": "UNOBSERVED",
    }


def _position_text_value_shape(value: Any, *, allow_empty: bool) -> tuple[str, str | None]:
    """Return only the fixed type bucket and V2-compatible text failure class."""

    if value is None:
        type_bucket = "null"
    elif type(value) is str:
        type_bucket = "str"
    elif type(value) is bytes:
        type_bucket = "bytes"
    elif type(value) is int:
        type_bucket = "int"
    elif type(value) is float:
        type_bucket = "float"
    else:
        type_bucket = "other"

    if type(value) is bytes:
        try:
            text = value.decode("ascii", errors="strict")
        except UnicodeDecodeError:
            return type_bucket, "ASCII_DECODE"
    elif type(value) is str:
        text = value
    else:
        return type_bucket, "TYPE"

    if len(text) > _POSITION_TEXT_PROBE_MAX_CHARS:
        return type_bucket, "TOO_LONG"
    if not text and not allow_empty:
        return type_bucket, "EMPTY"
    if text and all(ord(char) == 0 for char in text):
        return type_bucket, "NUL_ONLY"
    import unicodedata

    if any(unicodedata.category(char) == "Cc" for char in text):
        return type_bucket, "CONTROL"
    if text != text.strip():
        return type_bucket, "WHITESPACE"
    return type_bucket, None


def _project_position_text_probe(document: Mapping[str, Any]) -> dict[str, Any]:
    """Project the first invalid text shape in V2 projector source order."""

    if document.get("failure_code") != "position_text_invalid":
        return _unobserved_position_text_probe()
    query_facts = document.get("query_callbacks")
    if type(query_facts) is not list:
        return _unobserved_position_text_probe()
    by_phase_family = {}
    for item in query_facts:
        if type(item) is not dict or item.get("family") not in {"positions", "funds"}:
            continue
        key = (item.get("phase"), item.get("family"))
        by_phase_family[key] = item.get("callbacks")

    # V2 completes the baseline projection before the final projection. Within
    # each phase, _private_snapshot projects positions before account funds.
    for phase in ("baseline", "final"):
        for family in ("positions", "funds"):
            callbacks = by_phase_family.get((phase, family))
            if type(callbacks) is not list:
                continue
            for callback in callbacks:
                if (
                    type(callback) is not dict
                    or callback.get("row_present") is not True
                    or type(callback.get("row")) is not dict
                ):
                    continue
                row = callback["row"]
                for _, ordinal, field, allow_empty in _POSITION_TEXT_PROBE_FIELDS_BY_FAMILY[family]:
                    if field not in row:
                        type_bucket, category = "other", "MISSING"
                    else:
                        type_bucket, category = _position_text_value_shape(
                            row[field], allow_empty=allow_empty
                        )
                    if category is not None:
                        return {
                            "schema": _POSITION_TEXT_PROBE_SCHEMA,
                            "family": family,
                            "field_ordinal": ordinal,
                            "field": field,
                            "type_bucket": type_bucket,
                            "invalid_category": category,
                        }
    return _unobserved_position_text_probe()


def _valid_private_failure_document(
    document: Any,
    *,
    helpers: Mapping[str, Any],
    lifecycle: Any,
    pair_binding: Any,
    account_scope_sha256: str,
    credential_binding_sha256: str,
) -> dict[str, Any] | None:
    """Validate the native V2 failure artifact in memory and return counts only."""

    try:
        if type(document) is not dict or set(document) != _FAILURE_TOP_LEVEL_KEYS:
            return None
        if (
            document.get("protocol") != "iteration41.simnow-c01-private-failure.v1"
            or document.get("case_id") != CASE_ID
            or type(document.get("failure_code")) is not str
            or len(document["failure_code"]) > 256
            or document.get("worker_source_sha256") != _WORKER_SHA256
            or document.get("run_nonce") != lifecycle.run_nonce
            or document.get("parent_pid") != lifecycle.parent_pid
            or document.get("worker_pid") != lifecycle.worker_pid
            or document.get("pair_binding") != pair_binding.to_receipt_ref().to_dict()
            or document.get("account_scope_sha256") != account_scope_sha256
            or document.get("credential_binding_sha256") != credential_binding_sha256
        ):
            return None
        if (
            type(document.get("run_nonce")) is not str
            or not re.fullmatch(r"[0-9a-f]{32}", document["run_nonce"])
            or type(document.get("parent_pid")) is not int
            or document["parent_pid"] < 1
            or type(document.get("worker_pid")) is not int
            or document["worker_pid"] < 1
            or type(document.get("account_scope_sha256")) is not str
            or not _SHA256_RE.fullmatch(document["account_scope_sha256"])
            or type(document.get("credential_binding_sha256")) is not str
            or not _SHA256_RE.fullmatch(document["credential_binding_sha256"])
        ):
            return None

        client = document.get("client")
        if client is not None:
            if (
                type(client) is not dict
                or set(client) != {"instance_id", "client_generation", "arrival_generation"}
                or type(client.get("instance_id")) is not str
                or not re.fullmatch(r"[0-9a-f]{32}", client["instance_id"])
                or type(client.get("client_generation")) is not int
                or client["client_generation"] < 1
                or (
                    client.get("arrival_generation") is not None
                    and (
                        type(client["arrival_generation"]) is not int
                        or client["arrival_generation"] < 1
                    )
                )
            ):
                return None

        requests = document.get("requests")
        callbacks = document.get("callbacks")
        private_rows = document.get("private_auth_login_callback_rows")
        query_facts = document.get("query_callbacks")
        snapshots = document.get("snapshots")
        if (
            type(requests) is not list
            or len(requests) > 8
            or type(callbacks) is not list
            or len(callbacks) > MAX_PRIVATE_FAILURE_CALLBACKS
            or type(private_rows) is not list
            or len(private_rows) > MAX_PRIVATE_FAILURE_CALLBACKS
            or type(query_facts) is not list
            or len(query_facts) > 6
            or type(snapshots) is not list
            or len(snapshots) > 2
        ):
            return None
        if client is None and (requests or callbacks or private_rows or query_facts or snapshots):
            return None

        request_plan = (
            ("authenticate", None, None, "ReqAuthenticate"),
            ("login", None, None, "ReqUserLogin"),
            ("query", "baseline", "orders", "ReqQryOrder"),
            ("query", "baseline", "positions", "ReqQryInvestorPosition"),
            ("query", "baseline", "funds", "ReqQryTradingAccount"),
            ("query", "final", "orders", "ReqQryOrder"),
            ("query", "final", "positions", "ReqQryInvestorPosition"),
            ("query", "final", "funds", "ReqQryTradingAccount"),
        )
        protocol = helpers["protocol"]
        request_by_id: dict[int, dict[str, Any]] = {}
        for index, request in enumerate(requests):
            expected_kind, expected_phase, expected_family, expected_method = request_plan[index]
            if type(request) is not dict or set(request) != _FAILURE_REQUEST_KEYS:
                return None
            if (
                request.get("kind") != expected_kind
                or request.get("phase") != expected_phase
                or request.get("family") != expected_family
                or request.get("method") != expected_method
                or request.get("receipt_origin") != "local_native_invocation"
                or request.get("account_scope_sha256") != account_scope_sha256
                or request.get("credential_binding_sha256") != credential_binding_sha256
                or type(request.get("request_id")) is not int
                or request["request_id"] < 1
                or type(request.get("request_generation")) is not int
                or request["request_generation"] < 1
                or type(request.get("local_sequence")) is not int
                or request["local_sequence"] < 1
                or type(request.get("issued_at_utc")) is not str
                or not _WORKER_PROGRESS_UTC_RE.fullmatch(request["issued_at_utc"])
                or type(request.get("issued_monotonic_ns")) is not int
                or request["issued_monotonic_ns"] < 1
                or (
                    request.get("return_code") is not None
                    and (
                        type(request["return_code"]) is not int
                        or not -(2**31) <= request["return_code"] <= 2**31 - 1
                    )
                )
                or request.get("sdk_query_result") is not None
                and not _valid_json_payload(request["sdk_query_result"])
            ):
                return None
            if expected_kind != "query" and request.get("sdk_query_result") is not None:
                return None
            if request.get("sdk_query_result") is not None:
                if expected_kind != "query" or client is None:
                    return None
                try:
                    protocol._validate_sdk_query_result(
                        request["sdk_query_result"], request, client
                    )
                except Exception:
                    return None
            if request["request_id"] in request_by_id:
                return None
            request_by_id[request["request_id"]] = request

        callback_local_sequences: set[int] = set()
        query_callbacks_by_sequence: dict[int, dict[str, Any]] = {}
        for callback in callbacks:
            if type(callback) is not dict or set(callback) != _FAILURE_CALLBACK_KEYS:
                return None
            kind = callback.get("kind")
            if kind not in {"authenticate", "login", "query", "order_activity", "trade_activity"}:
                return None
            expected_names = {
                "authenticate": "OnRspAuthenticate",
                "login": "OnRspUserLogin",
                "orders": "OnRspQryOrder",
                "positions": "OnRspQryInvestorPosition",
                "funds": "OnRspQryTradingAccount",
                "order_activity": "OnRtnOrder",
                "trade_activity": "OnRtnTrade",
            }
            family = callback.get("family")
            if (
                callback.get("callback_name")
                != expected_names.get(family if kind == "query" else kind)
                or type(callback.get("client_instance_id")) is not str
                or type(callback.get("client_generation")) is not int
                or type(callback.get("arrival_generation")) is not int
                or type(callback.get("local_sequence")) is not int
                or callback["local_sequence"] < 1
                or callback["local_sequence"] in callback_local_sequences
                or type(callback.get("arrived_at_utc")) is not str
                or not _WORKER_PROGRESS_UTC_RE.fullmatch(callback["arrived_at_utc"])
                or type(callback.get("arrived_monotonic_ns")) is not int
                or callback["arrived_monotonic_ns"] < 1
                or callback.get("account_scope_sha256") != account_scope_sha256
                or callback.get("credential_binding_sha256") != credential_binding_sha256
            ):
                return None
            if client is None or (
                callback["client_instance_id"] != client["instance_id"]
                or callback["client_generation"] != client["client_generation"]
                or callback["arrival_generation"] != client["arrival_generation"]
            ):
                return None
            if kind == "query":
                if (
                    callback.get("phase") not in {"baseline", "final"}
                    or family not in {"orders", "positions", "funds"}
                    or type(callback.get("request_id")) is not int
                    or type(callback.get("request_generation")) is not int
                    or type(callback.get("row_present")) is not bool
                    or callback.get("is_last") is not None
                    and type(callback["is_last"]) is not bool
                ):
                    return None
                if (
                    callback["request_id"] not in request_by_id
                    or callback["request_generation"]
                    != request_by_id[callback["request_id"]]["request_generation"]
                ):
                    return None
            elif kind in {"authenticate", "login"}:
                if (
                    callback.get("phase") is not None
                    or callback.get("family") is not None
                    or type(callback.get("request_id")) is not int
                    or type(callback.get("request_generation")) is not int
                    or callback.get("row_present") is not None
                    or callback.get("is_last") is not None
                    and type(callback["is_last"]) is not bool
                ):
                    return None
            elif any(
                callback.get(name) is not None
                for name in ("phase", "family", "request_id", "request_generation", "row_present", "is_last")
            ):
                return None
            request = request_by_id.get(callback.get("request_id"))
            if kind in {"authenticate", "login", "query"} and (
                request is None
                or callback["request_generation"] != request["request_generation"]
                or callback["kind"] != request["kind"]
                or callback["phase"] != request["phase"]
                or callback["family"] != request["family"]
            ):
                return None
            try:
                protocol._validate_callback_error_facts(
                    callback, required=kind in {"authenticate", "login", "query"}
                )
            except Exception:
                return None
            if callback.get("row_present") is not None and type(callback["row_present"]) is not bool:
                return None
            if any(
                callback.get(name) is not None and type(callback[name]) is not str
                for name in ("session_id", "trading_day")
            ) or (
                callback.get("front_id") is not None
                and (type(callback["front_id"]) is not int or callback["front_id"] < 1)
            ):
                return None
            callback_local_sequences.add(callback["local_sequence"])
            if kind == "query":
                query_callbacks_by_sequence[callback["local_sequence"]] = callback

        for row in private_rows:
            if (
                type(row) is not dict
                or set(row) != _FAILURE_PRIVATE_ROW_KEYS
                or row.get("callback_name") not in {"OnRspAuthenticate", "OnRspUserLogin"}
                or type(row.get("request_id")) is not int
                or type(row.get("request_generation")) is not int
                or type(row.get("local_sequence")) is not int
                or type(row.get("row_present")) is not bool
                or row.get("capture_error") is not None
                and (type(row["capture_error"]) is not str or len(row["capture_error"]) > 256)
                or row.get("row") is not None
                and (type(row["row"]) is not dict or not _valid_json_payload(row["row"]))
            ):
                return None
            request = request_by_id.get(row["request_id"])
            if (
                request is None
                or request["kind"] != ("authenticate" if row["callback_name"] == "OnRspAuthenticate" else "login")
                or request["request_generation"] != row["request_generation"]
                or not any(
                    callback.get("callback_name") == row["callback_name"]
                    and callback.get("request_id") == row["request_id"]
                    and callback.get("local_sequence") == row["local_sequence"]
                    for callback in callbacks
                )
            ):
                return None

        query_event_count = 0
        phase_callback_counts = {"baseline": 0, "final": 0}
        seen_query_ids: set[int] = set()
        seen_query_callback_sequences: set[int] = set()
        for item in query_facts:
            if type(item) is not dict or set(item) != _FAILURE_QUERY_FACT_KEYS:
                return None
            request_id = item.get("request_id")
            query_request = request_by_id.get(request_id) if type(request_id) is int else None
            phase = item.get("phase")
            family = item.get("family")
            if request_id in seen_query_ids or type(item.get("callbacks")) is not list:
                return None
            if (
                query_request is None
                or query_request["kind"] != "query"
                or phase != query_request["phase"]
                or family != query_request["family"]
            ):
                return None
            nested_callbacks = item["callbacks"]
            if len(nested_callbacks) > MAX_PRIVATE_FAILURE_CALLBACKS:
                return None
            for nested in nested_callbacks:
                if (
                    type(nested) is not dict
                    or set(nested) != _FAILURE_QUERY_CALLBACK_KEYS
                    or type(nested.get("request_id")) is not int
                    or nested["request_id"] != request_id
                    or type(nested.get("callback_name")) is not str
                    or type(nested.get("request_generation")) is not int
                    or type(nested.get("local_sequence")) is not int
                    or type(nested.get("arrived_at_utc")) is not str
                    or not _WORKER_PROGRESS_UTC_RE.fullmatch(nested["arrived_at_utc"])
                    or type(nested.get("arrived_monotonic_ns")) is not int
                    or type(nested.get("row_present")) is not bool
                    or nested.get("row") is not None
                    and (type(nested["row"]) is not dict or not _valid_json_payload(nested["row"]))
                    or nested.get("callback_name")
                    != {
                        "orders": "OnRspQryOrder",
                        "positions": "OnRspQryInvestorPosition",
                        "funds": "OnRspQryTradingAccount",
                    }[family]
                    or nested.get("request_generation") != query_request["request_generation"]
                    or nested.get("is_last") is not None
                    and type(nested["is_last"]) is not bool
                ):
                    return None
                try:
                    protocol._validate_callback_error_facts(nested, required=True)
                except Exception:
                    return None
                sequence = nested["local_sequence"]
                top_level = query_callbacks_by_sequence.get(sequence)
                if sequence in seen_query_callback_sequences or top_level is None:
                    return None
                if any(
                    nested.get(nested_key) != top_level.get(top_key)
                    for nested_key, top_key in (
                        ("callback_name", "callback_name"),
                        ("request_id", "request_id"),
                        ("error_id", "error_id"),
                        ("rsp_info_present", "rsp_info_present"),
                        ("error_semantics", "error_semantics"),
                        ("is_last", "is_last"),
                        ("request_generation", "request_generation"),
                        ("local_sequence", "local_sequence"),
                        ("arrived_at_utc", "arrived_at_utc"),
                        ("arrived_monotonic_ns", "arrived_monotonic_ns"),
                        ("row_present", "row_present"),
                    )
                ) or top_level.get("phase") != phase or top_level.get("family") != family:
                    return None
                seen_query_callback_sequences.add(sequence)
            if phase in phase_callback_counts:
                phase_callback_counts[phase] += len(nested_callbacks)
            query_event_count += len(nested_callbacks)
            seen_query_ids.add(request_id)
        if (
            query_event_count > MAX_PRIVATE_FAILURE_CALLBACKS
            or len(seen_query_callback_sequences) != len(query_callbacks_by_sequence)
        ):
            return None

        expected_snapshot_phases = ("baseline", "final")
        for index, snapshot in enumerate(snapshots):
            if type(snapshot) is not dict or set(snapshot) != _FAILURE_SNAPSHOT_KEYS:
                return None
            phase = expected_snapshot_phases[index]
            if (
                snapshot.get("phase") != phase
                or snapshot.get("artifact_ref") != "snapshots/{}.json".format(phase)
                or type(snapshot.get("artifact_sha256")) is not str
                or not _SHA256_RE.fullmatch(snapshot["artifact_sha256"])
                or type(snapshot.get("client_instance_id")) is not str
                or client is None
                or snapshot["client_instance_id"] != client["instance_id"]
                or snapshot.get("client_generation") != client["client_generation"]
                or snapshot.get("arrival_generation") != client["arrival_generation"]
                or type(snapshot.get("session_id")) is not str
                or type(snapshot.get("trading_day")) is not str
                or not re.fullmatch(r"[0-9]{8}", snapshot["trading_day"])
                or type(snapshot.get("queries")) is not dict
                or set(snapshot["queries"]) != {"orders", "positions", "funds"}
            ):
                return None
            for digest_name in (
                "open_order_refs_sha256",
                "order_economics_sha256",
                "positions_sha256",
                "funds_sha256",
            ):
                if type(snapshot.get(digest_name)) is not str or not _SHA256_RE.fullmatch(snapshot[digest_name]):
                    return None
            for family, query in snapshot["queries"].items():
                if (
                    type(query) is not dict
                    or set(query) != {"request_id", "callback_count", "row_count", "first_sequence", "terminal_sequence"}
                    or any(type(query.get(name)) is not int or query[name] < 1 for name in ("request_id", "callback_count", "first_sequence", "terminal_sequence"))
                    or type(query.get("row_count")) is not int
                    or query["row_count"] < 0
                ):
                    return None

        write_counters = document.get("write_counters")
        if write_counters is not None and (
            type(write_counters) is not dict
            or set(write_counters) != {"ReqOrderInsert", "ReqOrderAction"}
            or any(
                type(write_counters[name]) is not int or not 0 <= write_counters[name] <= 1_000_000
                for name in ("ReqOrderInsert", "ReqOrderAction")
            )
        ):
            return None
        native_close = document.get("native_close")
        if native_close is not None and (
            type(native_close) is not dict
            or set(native_close) != {"receipt_type", "join_required", "join_completed", "native_released", "thread_alive", "timed_out"}
            or native_close.get("receipt_type") != "CtpNativeStopReceipt"
            or any(type(native_close.get(name)) is not bool for name in ("join_required", "join_completed", "native_released", "thread_alive", "timed_out"))
        ):
            return None
        close_error = document.get("native_close_error_code")
        if close_error is not None and (type(close_error) is not str or len(close_error) > 256):
            return None

        ordinal = _FAILURE_CODE_ORDINALS.get(document["failure_code"], 0)
        return {
            "schema": _WORKER_FAILURE_DIAGNOSTIC_SCHEMA,
            "status": "verified",
            "failure_code_ordinal": ordinal,
            "request_count": len(requests),
            "callback_count": len(callbacks),
            "auth_login_callback_row_count": len(private_rows),
            "query_request_count": sum(request["kind"] == "query" for request in requests),
            "query_event_count": query_event_count,
            "baseline_query_callback_count": phase_callback_counts["baseline"],
            "final_query_callback_count": phase_callback_counts["final"],
            "snapshot_count": len(snapshots),
            "baseline_snapshot_count": sum(snapshot["phase"] == "baseline" for snapshot in snapshots),
            "final_snapshot_count": sum(snapshot["phase"] == "final" for snapshot in snapshots),
            "order_insert_requests": (
                write_counters["ReqOrderInsert"] if write_counters is not None else None
            ),
            "order_cancel_requests": (
                write_counters["ReqOrderAction"] if write_counters is not None else None
            ),
            "native_close_status": "present" if native_close is not None else "absent",
            "position_text_probe": _project_position_text_probe(document),
        }
    except Exception:
        return None


def _failure_lifecycle_safe(helpers: Mapping[str, Any], process: Any) -> bool:
    """Require parent-observed clean nonzero worker teardown before private read."""

    try:
        if type(process) is not helpers["supervisor"].C01SupervisorResult:
            return False
        lifecycle = process.process_lifecycle
        return (
            process.status == "BLOCKED"
            and process.reason == "worker_exit_nonzero"
            and process.worker_receipt is None
            and type(lifecycle) is helpers["protocol"].C01ProcessLifecycleReceipt
            and lifecycle.status == "BLOCKED"
            and lifecycle.reason == "worker_exit_nonzero"
            and lifecycle.containment == "windows_job"
            and lifecycle.assigned_before_resume is True
            and lifecycle.stdin_fully_sent is True
            and lifecycle.stdout_eof is True
            and lifecycle.stderr_eof is True
            and lifecycle.process_exit_observed is True
            and type(lifecycle.process_exit_code) is int
            and lifecycle.process_exit_code != 0
            and type(lifecycle.job_active_count) is int
            and lifecycle.job_active_count == 0
            and lifecycle.handles_closed is True
            and lifecycle.timed_out is False
            and lifecycle.forced_kill is False
            and type(lifecycle.worker_pid) is int
            and lifecycle.worker_pid > 0
            and lifecycle.worker_pid != os.getpid()
            and lifecycle.parent_pid == os.getpid()
            and type(lifecycle.run_nonce) is str
            and re.fullmatch(r"[0-9a-f]{32}", lifecycle.run_nonce) is not None
            and lifecycle.worker_source_sha256 == _WORKER_SHA256
        )
    except Exception:
        return False


def _read_worker_failure_diagnostic(
    owner: ModuleType,
    helpers: Mapping[str, Any],
    paths: Any,
    process: Any,
    pair_binding: Any,
    account_scope_sha256: str,
    credential_binding_sha256: str,
    *,
    deadline: float,
) -> dict[str, Any]:
    """Read only this invocation's failure.json under the held private lease."""

    unavailable = _unobserved_failure_diagnostic()
    try:
        if time.monotonic() >= deadline or not _failure_lifecycle_safe(helpers, process):
            return unavailable
        lifecycle = process.process_lifecycle
        entries = owner._directory_entries(paths.evidence.path)
        failure_entries = []
        for entry in entries:
            if entry.name == "snapshots" and entry.is_dir():
                continue
            if _WORKER_PROGRESS_FILENAME_RE.fullmatch(entry.name) and not entry.is_dir():
                continue
            if entry.name == "failure.json" and not entry.is_dir():
                failure_entries.append(entry)
                continue
            return unavailable
        if len(failure_entries) != 1:
            return unavailable
        private = helpers["private"]
        r3_cli = helpers["r3_cli"]
        api = private._api()
        sid = api.current_sid()
        with r3_cli._locked_readonly_file(failure_entries[0], private, api) as (handle, _identity):
            api.verify_acl(handle, sid, directory=False)
            raw = r3_cli._read_bounded_handle(api, handle, MAX_PRIVATE_FAILURE_BYTES)
        if time.monotonic() >= deadline or type(raw) is not bytes or not raw.endswith(b"\n"):
            return unavailable
        if len(raw) > MAX_PRIVATE_FAILURE_BYTES:
            return unavailable
        document = json.loads(
            raw.decode("ascii"),
            object_pairs_hook=_strict_object,
            parse_constant=lambda _value: (_ for _ in ()).throw(ValueError()),
        )
        canonical = (
            json.dumps(document, ensure_ascii=True, allow_nan=False, sort_keys=True, separators=(",", ":"))
            .encode("ascii")
            + b"\n"
        )
        if raw != canonical:
            return unavailable
        summary = _valid_private_failure_document(
            document,
            helpers=helpers,
            lifecycle=lifecycle,
            pair_binding=pair_binding,
            account_scope_sha256=account_scope_sha256,
            credential_binding_sha256=credential_binding_sha256,
        )
        return summary if summary is not None else unavailable
    except Exception:
        return unavailable


def _observation_count(value: Any, maximum: int) -> bool:
    return value is None or (type(value) is int and 0 <= value <= maximum)


def _validate_failure_diagnostic(value: Any) -> dict[str, Any]:
    if type(value) is not dict or set(value) != _FAILURE_DIAGNOSTIC_KEYS:
        raise ValueError("worker_failure_diagnostic_invalid")
    if (
        value.get("schema") != _WORKER_FAILURE_DIAGNOSTIC_SCHEMA
        or value.get("status") not in {"verified", "UNOBSERVED"}
    ):
        raise ValueError("worker_failure_diagnostic_invalid")
    limits = {
        "failure_code_ordinal": len(_FAILURE_CODE_LITERALS),
        "request_count": 8,
        "callback_count": MAX_PRIVATE_FAILURE_CALLBACKS,
        "auth_login_callback_row_count": MAX_PRIVATE_FAILURE_CALLBACKS,
        "query_request_count": 6,
        "query_event_count": MAX_PRIVATE_FAILURE_CALLBACKS,
        "baseline_query_callback_count": MAX_PRIVATE_FAILURE_CALLBACKS,
        "final_query_callback_count": MAX_PRIVATE_FAILURE_CALLBACKS,
        "snapshot_count": 2,
        "baseline_snapshot_count": 1,
        "final_snapshot_count": 1,
        "order_insert_requests": 1_000_000,
        "order_cancel_requests": 1_000_000,
    }
    for name, maximum in limits.items():
        if not _observation_count(value.get(name), maximum):
            raise ValueError("worker_failure_diagnostic_invalid")
    if value.get("native_close_status") not in {"present", "absent", "UNOBSERVED"}:
        raise ValueError("worker_failure_diagnostic_invalid")
    probe = value.get("position_text_probe")
    if type(probe) is not dict or set(probe) != {
        "schema", "family", "field_ordinal", "field", "type_bucket", "invalid_category"
    } or probe.get("schema") != _POSITION_TEXT_PROBE_SCHEMA:
        raise ValueError("worker_failure_diagnostic_invalid")
    if (
        type(probe.get("invalid_category")) is not str
        or probe.get("invalid_category") not in _POSITION_TEXT_PROBE_CATEGORIES
    ):
        raise ValueError("worker_failure_diagnostic_invalid")
    if probe["invalid_category"] == "UNOBSERVED":
        if any(probe.get(name) is not None for name in ("family", "field_ordinal", "field", "type_bucket")):
            raise ValueError("worker_failure_diagnostic_invalid")
    else:
        family = probe.get("family")
        ordinal = probe.get("field_ordinal")
        field = probe.get("field")
        if (
            type(family) is not str
            or family not in _POSITION_TEXT_PROBE_FIELDS_BY_FAMILY
            or type(ordinal) is not int
            or type(field) is not str
            or type(probe.get("type_bucket")) is not str
            or probe.get("type_bucket") not in _POSITION_TEXT_PROBE_TYPES
        ):
            raise ValueError("worker_failure_diagnostic_invalid")
        expected_fields = _POSITION_TEXT_PROBE_FIELDS_BY_FAMILY[family]
        if not any(item[1] == ordinal and item[2] == field for item in expected_fields):
            raise ValueError("worker_failure_diagnostic_invalid")
    if (
        probe["invalid_category"] != "UNOBSERVED"
        and value.get("failure_code_ordinal")
        != _FAILURE_CODE_ORDINALS.get("position_text_invalid")
    ):
        raise ValueError("worker_failure_diagnostic_invalid")
    if value["status"] == "UNOBSERVED":
        if any(value.get(name) is not None for name in limits) or value[
            "native_close_status"
        ] != "UNOBSERVED" or probe["invalid_category"] != "UNOBSERVED":
            raise ValueError("worker_failure_diagnostic_invalid")
    elif (
        any(value.get(name) is None for name in limits if name not in {
            "order_insert_requests", "order_cancel_requests"
        })
        or value["native_close_status"] not in {"present", "absent"}
        or value["baseline_snapshot_count"] + value["final_snapshot_count"]
        != value["snapshot_count"]
        or value["baseline_query_callback_count"] + value["final_query_callback_count"]
        != value["query_event_count"]
        or value["query_request_count"] > value["request_count"]
    ):
        raise ValueError("worker_failure_diagnostic_invalid")
    return dict(value)


def _validate_worker_observation(value: Any) -> dict[str, Any] | None:
    """Validate and copy the fixed, value-free same-call worker projection."""

    if value is None:
        return None
    observation_keys = {
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
    lifecycle_keys = {
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
    progress_keys = {"status", "last_stage", "last_event", "record_count"}
    count_limits = {
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
    if (
        type(value) is not dict
        or set(value) != observation_keys
        or value.get("schema") != _WORKER_OBSERVATION_SCHEMA
        or value.get("authority") != "NONE"
        or value.get("supervisor_result_type") not in _WORKER_OBSERVATION_SUPERVISOR_TYPES
        or value.get("supervisor_reason")
        not in (_WORKER_OBSERVATION_SUPERVISOR_REASONS | {"UNKNOWN", "UNOBSERVED"})
        or value.get("supervisor_status") not in {"BLOCKED", "UNKNOWN", "UNOBSERVED"}
        or value.get("lifecycle_type") not in _WORKER_OBSERVATION_LIFECYCLE_TYPES
        or value.get("receipt_type") not in _WORKER_OBSERVATION_RECEIPT_TYPES
        or value.get("write_policy") != "NO_WRITE"
        or type(value.get("writes")) is not int
        or value.get("writes") != 0
    ):
        raise ValueError("worker_observation_invalid")
    lifecycle = value.get("lifecycle")
    progress = value.get("progress")
    counts = value.get("request_counts")
    failure_diagnostic = _validate_failure_diagnostic(value.get("failure_diagnostic"))
    if (
        type(lifecycle) is not dict
        or set(lifecycle) != lifecycle_keys
        or type(progress) is not dict
        or set(progress) != progress_keys
        or type(counts) is not dict
        or set(counts) != set(count_limits)
    ):
        raise ValueError("worker_observation_invalid")
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
            raise ValueError("worker_observation_invalid")
    if lifecycle["process_exit_code"] not in {
        "ZERO",
        "TWO",
        "OTHER_NONZERO",
        "UNOBSERVED",
        "INVALID",
    }:
        raise ValueError("worker_observation_invalid")
    if lifecycle["job_active_status"] not in {"ZERO", "NONZERO", "UNOBSERVED", "INVALID"}:
        raise ValueError("worker_observation_invalid")
    if lifecycle["containment"] not in {
        "windows_job",
        "not_started",
        "other",
        "UNKNOWN",
        "UNOBSERVED",
    } or lifecycle["status"] not in {"BLOCKED", "UNKNOWN", "UNOBSERVED"}:
        raise ValueError("worker_observation_invalid")
    progress_status = progress.get("status")
    if progress_status not in _WORKER_OBSERVATION_PROGRESS_STATUSES:
        raise ValueError("worker_observation_invalid")
    if progress_status == "UNOBSERVED":
        if (
            progress.get("last_stage") is not None
            or progress.get("last_event") is not None
            or progress.get("record_count") is not None
        ):
            raise ValueError("worker_observation_invalid")
    elif (
        type(progress.get("record_count")) is not int
        or not 0 <= progress["record_count"] <= MAX_WORKER_PROGRESS_RECORDS
    ):
        raise ValueError("worker_observation_invalid")
    elif progress_status == "verified":
        if (
            progress["record_count"] < 1
            or type(progress.get("last_stage")) is not str
            or progress["last_stage"] not in _WORKER_PROGRESS_STAGE_EVENTS
            or type(progress.get("last_event")) is not str
            or progress["last_event"] not in _WORKER_PROGRESS_STAGE_EVENTS[progress["last_stage"]]
        ):
            raise ValueError("worker_observation_invalid")
    elif (
        progress["record_count"] != 0
        or progress.get("last_stage") is not None
        or progress.get("last_event") is not None
    ):
        raise ValueError("worker_observation_invalid")
    for name, maximum in count_limits.items():
        if not _observation_count(counts.get(name), maximum):
            raise ValueError("worker_observation_invalid")
    if value["receipt_type"] == "expected":
        for name in (
            "authenticate_return_code_observed",
            "login_return_code_observed",
            "query_return_code_observed",
            "order_insert_requests",
            "order_cancel_requests",
        ):
            if counts[name] is None:
                raise ValueError("worker_observation_invalid")
        if (
            any(
                counts[zero_name] is not None
                and counts[zero_name] > counts[observed_name]
                for zero_name, observed_name in (
                    ("authenticate_return_code_zero", "authenticate_return_code_observed"),
                    ("login_return_code_zero", "login_return_code_observed"),
                    ("query_return_code_zero", "query_return_code_observed"),
                )
            )
            or any(
                (counts[zero_name] is None) != (counts[observed_name] == 0)
                for zero_name, observed_name in (
                    ("authenticate_return_code_zero", "authenticate_return_code_observed"),
                    ("login_return_code_zero", "login_return_code_observed"),
                    ("query_return_code_zero", "query_return_code_observed"),
                )
            )
        ):
            raise ValueError("worker_observation_invalid")
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
        raise ValueError("worker_observation_invalid")
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
        raise ValueError("worker_observation_invalid")
    if failure_diagnostic["status"] == "verified":
        if (
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
            raise ValueError("worker_observation_invalid")
    if failure_diagnostic["status"] == "verified":
        if (
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
            raise ValueError("worker_observation_invalid")
    if value["supervisor_result_type"] == "unobserved":
        if (
            value["supervisor_reason"] != "UNOBSERVED"
            or value["supervisor_status"] != "UNOBSERVED"
            or value["lifecycle_type"] != "unobserved"
            or value["receipt_type"] != "unobserved"
            or progress_status != "UNOBSERVED"
        ):
            raise ValueError("worker_observation_invalid")
    if value["lifecycle_type"] == "unobserved":
        if (
            value["receipt_type"] != "unobserved"
            or progress_status != "UNOBSERVED"
            or any(
                lifecycle.get(name) is not None
                for name in (
                    "assignment_before_resume",
                    "stdin_fully_sent",
                    "stdout_eof",
                    "stderr_eof",
                    "process_exit_observed",
                    "handles_closed",
                    "timed_out",
                    "forced_kill",
                )
            )
            or lifecycle.get("process_exit_code") != "UNOBSERVED"
            or lifecycle.get("job_active_status") != "UNOBSERVED"
            or lifecycle.get("containment") != "UNOBSERVED"
            or lifecycle.get("status") != "UNOBSERVED"
            or any(counts.get(name) is not None for name in count_limits)
            or failure_diagnostic["status"] != "UNOBSERVED"
        ):
            raise ValueError("worker_observation_invalid")
    copied_lifecycle = dict(lifecycle)
    copied_progress = dict(progress)
    copied_counts = dict(counts)
    return {
        "schema": _WORKER_OBSERVATION_SCHEMA,
        "authority": "NONE",
        "supervisor_result_type": value["supervisor_result_type"],
        "supervisor_reason": value["supervisor_reason"],
        "supervisor_status": value["supervisor_status"],
        "lifecycle_type": value["lifecycle_type"],
        "receipt_type": value["receipt_type"],
        "lifecycle": copied_lifecycle,
        "progress": copied_progress,
        "request_counts": copied_counts,
        "failure_diagnostic": failure_diagnostic,
        "write_policy": "NO_WRITE",
        "writes": 0,
    }


def _project_worker_observation(
    helpers: Mapping[str, Any],
    process: Any,
    progress: Any,
    failure_diagnostic: Any = None,
) -> dict[str, Any] | None:
    """Project only fixed categories and bounded counts from current-call facts."""

    try:
        supervisor = helpers["supervisor"]
        protocol = helpers["protocol"]
        process_type = supervisor.C01SupervisorResult
        lifecycle_class = protocol.C01ProcessLifecycleReceipt
        receipt_class = protocol.C01WorkerReceipt
        process_expected = type(process) is process_type
        process_type_status = (
            "expected" if process_expected else ("unobserved" if process is None else "unexpected")
        )
        lifecycle = process.process_lifecycle if process_expected else None
        lifecycle_expected = type(lifecycle) is lifecycle_class
        lifecycle_type_status = (
            "expected"
            if lifecycle_expected
            else ("unobserved" if lifecycle is None else "unexpected")
        )
        reason = "UNOBSERVED"
        supervisor_status = "UNOBSERVED"
        receipt = None
        receipt_type_status = "unobserved"
        if process_expected:
            raw_reason = getattr(process, "reason", None)
            reason = (
                raw_reason
                if type(raw_reason) is str and raw_reason in _WORKER_OBSERVATION_SUPERVISOR_REASONS
                else "UNKNOWN"
            )
            raw_status = getattr(process, "status", None)
            supervisor_status = "BLOCKED" if raw_status == "BLOCKED" else "UNKNOWN"
            receipt = getattr(process, "worker_receipt", None)
            if not lifecycle_expected:
                receipt_type_status = "unobserved"
            elif receipt is None:
                receipt_type_status = "none"
            elif type(receipt) is receipt_class:
                receipt_type_status = "expected"
            else:
                receipt_type_status = "unexpected"
        if lifecycle_expected:
            bool_names = (
                "assigned_before_resume",
                "stdin_fully_sent",
                "stdout_eof",
                "stderr_eof",
                "process_exit_observed",
                "handles_closed",
                "timed_out",
                "forced_kill",
            )
            lifecycle_values = {}
            for name in bool_names:
                field_value = getattr(lifecycle, name, None)
                if field_value is not None and type(field_value) is not bool:
                    return None
                output_name = (
                    "assignment_before_resume"
                    if name == "assigned_before_resume"
                    else name
                )
                lifecycle_values[output_name] = field_value
            exit_code = getattr(lifecycle, "process_exit_code", None)
            if exit_code is None:
                exit_status = "UNOBSERVED"
            elif type(exit_code) is not int:
                exit_status = "INVALID"
            elif exit_code == 0:
                exit_status = "ZERO"
            elif exit_code == 2:
                exit_status = "TWO"
            else:
                exit_status = "OTHER_NONZERO"
            active = getattr(lifecycle, "job_active_count", None)
            if active is None:
                active_status = "UNOBSERVED"
            elif type(active) is not int or not 0 <= active <= 128:
                active_status = "INVALID"
            else:
                active_status = "ZERO" if active == 0 else "NONZERO"
            containment_value = getattr(lifecycle, "containment", None)
            containment = (
                containment_value
                if type(containment_value) is str
                and containment_value in {"windows_job", "not_started"}
                else ("UNOBSERVED" if containment_value is None else "other")
            )
            lifecycle_status_value = getattr(lifecycle, "status", None)
            lifecycle_status = (
                "BLOCKED" if lifecycle_status_value == "BLOCKED" else "UNKNOWN"
            )
        else:
            lifecycle_values = {
                name: None
                for name in (
                    "assignment_before_resume",
                    "stdin_fully_sent",
                    "stdout_eof",
                    "stderr_eof",
                    "process_exit_observed",
                    "handles_closed",
                    "timed_out",
                    "forced_kill",
                )
            }
            exit_status = "UNOBSERVED"
            active_status = "UNOBSERVED"
            containment = "UNOBSERVED"
            lifecycle_status = "UNOBSERVED"
        safe_progress = _safe_progress_summary(progress)
        progress_status = (
            "UNOBSERVED" if not process_expected or not lifecycle_expected else safe_progress["status"]
        )
        if progress_status == "verified":
            records = safe_progress["records"]

            def event_count(stage_names: Sequence[str], event_name: str) -> int:
                return sum(
                    1
                    for item in records
                    if item["stage"] in stage_names and item["event"] == event_name
                )

            auth_attempts = event_count(("authenticate_request",), "begin")
            login_attempts = event_count(("login_request",), "begin")
            query_stages = (
                "baseline_orders_request",
                "baseline_positions_request",
                "baseline_funds_request",
                "final_orders_request",
                "final_positions_request",
                "final_funds_request",
            )
            query_attempts = event_count(query_stages, "begin")
            auth_callback_first = event_count(("authenticate_callback",), "callback_first")
            auth_callback_terminal = event_count(("authenticate_callback",), "callback_terminal")
            login_callback_first = event_count(("login_callback",), "callback_first")
            login_callback_terminal = event_count(("login_callback",), "callback_terminal")
            query_callback_stages = (
                "baseline_orders_callback",
                "baseline_positions_callback",
                "baseline_funds_callback",
                "final_orders_callback",
                "final_positions_callback",
                "final_funds_callback",
            )
            query_callback_first = event_count(query_callback_stages, "callback_first")
            query_callback_terminal = event_count(query_callback_stages, "callback_terminal")
            last_stage = safe_progress["last_stage"]
            last_event = safe_progress["last_event"]
            progress_count = safe_progress["record_count"]
        else:
            auth_attempts = login_attempts = query_attempts = None
            auth_callback_first = auth_callback_terminal = None
            login_callback_first = login_callback_terminal = None
            query_callback_first = query_callback_terminal = None
            last_stage = last_event = None
            progress_count = None if progress_status == "UNOBSERVED" else safe_progress["record_count"]
        auth_rc_observed = auth_rc_zero = None
        login_rc_observed = login_rc_zero = None
        query_rc_observed = query_rc_zero = None
        order_insert_requests = order_cancel_requests = None
        if receipt_type_status == "expected":
            try:
                receipt_document = receipt.to_dict()
                if type(receipt_document) is not dict:
                    raise ValueError
                protocol._validate_worker_shape(receipt_document)
                requests = receipt_document["requests"]
                auth_code = requests[0]["return_code"]
                login_code = requests[1]["return_code"]
                query_codes = [item["return_code"] for item in requests[2:]]
                auth_rc_observed = int(auth_code is not None)
                auth_rc_zero = int(auth_code == 0) if auth_code is not None else None
                login_rc_observed = int(login_code is not None)
                login_rc_zero = int(login_code == 0) if login_code is not None else None
                query_rc_observed = sum(code is not None for code in query_codes)
                query_rc_zero = (
                    sum(code == 0 for code in query_codes if code is not None)
                    if query_rc_observed
                    else None
                )
                counters = receipt_document["write_counters"]
                order_insert_requests = counters["ReqOrderInsert"]
                order_cancel_requests = counters["ReqOrderAction"]
                if any(
                    type(item) is not int or not 0 <= item <= 1_000_000
                    for item in (order_insert_requests, order_cancel_requests)
                ):
                    raise ValueError
            except Exception:
                receipt_type_status = "invalid"
                auth_rc_observed = auth_rc_zero = None
                login_rc_observed = login_rc_zero = None
                query_rc_observed = query_rc_zero = None
                order_insert_requests = order_cancel_requests = None
        observation = {
            "schema": _WORKER_OBSERVATION_SCHEMA,
            "authority": "NONE",
            "supervisor_result_type": process_type_status,
            "supervisor_reason": reason,
            "supervisor_status": supervisor_status,
            "lifecycle_type": lifecycle_type_status,
            "receipt_type": receipt_type_status,
            "lifecycle": {
                **lifecycle_values,
                "process_exit_code": exit_status,
                "job_active_status": active_status,
                "containment": containment,
                "status": lifecycle_status,
            },
            "progress": {
                "status": progress_status,
                "last_stage": last_stage,
                "last_event": last_event,
                "record_count": progress_count,
            },
            "failure_diagnostic": _validate_failure_diagnostic(
                failure_diagnostic
                if failure_diagnostic is not None
                else _unobserved_failure_diagnostic()
            ),
            "request_counts": {
                "authenticate_attempts": auth_attempts,
                "authenticate_return_code_observed": auth_rc_observed,
                "authenticate_return_code_zero": auth_rc_zero,
                "authenticate_callback_first": auth_callback_first,
                "authenticate_callback_terminal": auth_callback_terminal,
                "login_attempts": login_attempts,
                "login_return_code_observed": login_rc_observed,
                "login_return_code_zero": login_rc_zero,
                "login_callback_first": login_callback_first,
                "login_callback_terminal": login_callback_terminal,
                "query_attempts": query_attempts,
                "query_return_code_observed": query_rc_observed,
                "query_return_code_zero": query_rc_zero,
                "query_callback_first": query_callback_first,
                "query_callback_terminal": query_callback_terminal,
                "order_insert_requests": order_insert_requests,
                "order_cancel_requests": order_cancel_requests,
            },
            "write_policy": "NO_WRITE",
            "writes": 0,
        }
        return _validate_worker_observation(observation)
    except Exception:
        return None


def _read_worker_progress(
    owner: ModuleType,
    helpers: Mapping[str, Any],
    paths: Any,
    process: Any,
    pair_binding: Any,
    account_scope_sha256: str,
    credential_binding_sha256: str,
) -> dict[str, Any]:
    """Read and verify only fixed progress files from the current private run."""

    unavailable = _empty_progress_summary("unavailable")
    try:
        if type(process) is not helpers["supervisor"].C01SupervisorResult:
            return unavailable
        lifecycle = process.process_lifecycle
        if type(lifecycle) is not helpers["protocol"].C01ProcessLifecycleReceipt:
            return unavailable
        evidence = paths.evidence.path
        entries = owner._directory_entries(evidence)
        progress_paths = []
        for entry in entries:
            if entry.name == "snapshots" or entry.name == "failure.json":
                continue
            if not _WORKER_PROGRESS_FILENAME_RE.fullmatch(entry.name) or entry.is_dir():
                return _empty_progress_summary("invalid", getattr(lifecycle, "worker_pid", None))
            progress_paths.append(entry)
        if len(progress_paths) > MAX_WORKER_PROGRESS_RECORDS:
            return _empty_progress_summary("invalid", getattr(lifecycle, "worker_pid", None))
        private = helpers["private"]
        r3_cli = helpers["r3_cli"]
        api = private._api()
        sid = api.current_sid()
        payloads: dict[str, bytes] = {}
        total_bytes = 0
        for path in progress_paths:
            with r3_cli._locked_readonly_file(path, private, api) as (handle, _identity):
                api.verify_acl(handle, sid, directory=False)
                raw = r3_cli._read_bounded_handle(api, handle, MAX_WORKER_PROGRESS_RECORD_BYTES)
            total_bytes += len(raw)
            if total_bytes > MAX_WORKER_PROGRESS_TOTAL_BYTES:
                return unavailable
            payloads[path.name] = raw
        pair_ref = pair_binding.to_receipt_ref().to_dict()
        return _progress_summary(
            payloads,
            run_nonce=lifecycle.run_nonce,
            parent_pid=lifecycle.parent_pid,
            worker_pid=lifecycle.worker_pid,
            worker_source_sha256=_WORKER_SHA256,
            pair_binding=pair_ref,
            account_scope_sha256=account_scope_sha256,
            credential_binding_sha256=credential_binding_sha256,
        )
    except Exception:
        return unavailable


def _diagnostic_stage_intents_document(
    helpers: Mapping[str, Any], process: Any, pair_binding: Any
) -> dict[str, Any] | None:
    """Validate and retain the supervisor's typed, local-only stage prefix."""

    supervisor = helpers["supervisor"]
    protocol = helpers["protocol"]
    if type(process) is not supervisor.C01SupervisorResult:
        raise _IssuerError("diagnostic_intent_result_invalid")
    lifecycle = process.process_lifecycle
    if type(lifecycle) is not protocol.C01ProcessLifecycleReceipt:
        raise _IssuerError("diagnostic_intent_lifecycle_invalid")
    if process.reason == "candidate_transport_complete":
        if process.diagnostic_intents or process.diagnostic_intents_error is not None:
            raise _IssuerError("diagnostic_intent_unexpected")
        return None
    if type(pair_binding) is not protocol.C01PairBinding:
        raise _IssuerError("diagnostic_intent_pair_binding_invalid")
    pair_ref = pair_binding.to_receipt_ref()
    if type(pair_ref) is not protocol.C01PairBindingRef:
        raise _IssuerError("diagnostic_intent_pair_binding_invalid")
    expected_pair_ref = pair_ref.to_dict()
    intents = process.diagnostic_intents
    error = process.diagnostic_intents_error
    if (
        type(intents) is not tuple
        or len(intents) > supervisor.MAX_DIAGNOSTIC_INTENT_RECORDS
        or (error is not None and error not in supervisor._DIAGNOSTIC_INTENT_ERRORS)
    ):
        raise _IssuerError("diagnostic_intent_shape_invalid")

    records = []
    for sequence, intent in enumerate(intents, start=1):
        if (
            type(intent) is not supervisor.C01StageIntent
            or type(intent.sequence) is not int
            or intent.sequence != sequence
            or type(intent.stage) is not str
            or intent.stage not in supervisor._DIAGNOSTIC_INTENT_STAGES
            or type(intent.event) is not str
            or intent.event not in supervisor._DIAGNOSTIC_INTENT_EVENTS
            or type(intent.run_nonce) is not str
            or not re.fullmatch(r"[0-9a-f]{32}", intent.run_nonce)
            or intent.run_nonce != lifecycle.run_nonce
            or type(intent.parent_pid) is not int
            or intent.parent_pid != lifecycle.parent_pid
            or type(intent.worker_pid) is not int
            or intent.worker_pid != lifecycle.worker_pid
            or type(intent.worker_source_sha256) is not str
            or intent.worker_source_sha256 != _WORKER_SHA256
            or type(intent.pair_binding_ref) is not protocol.C01PairBindingRef
            or intent.pair_binding_ref.to_dict() != expected_pair_ref
        ):
            raise _IssuerError("diagnostic_intent_binding_invalid")
        records.append(
            {
                "protocol": supervisor._DIAGNOSTIC_INTENT_PROTOCOL,
                "version": supervisor._DIAGNOSTIC_INTENT_VERSION,
                "case_id": CASE_ID,
                "sequence": sequence,
                "stage": intent.stage,
                "event": intent.event,
                "run_nonce": intent.run_nonce,
                "parent_pid": intent.parent_pid,
                "worker_pid": intent.worker_pid,
                "worker_source_sha256": intent.worker_source_sha256,
                "pair_binding_ref": expected_pair_ref,
            }
        )
    if process.reason == "diagnostic_profile_only" and (error is not None or not records):
        raise _IssuerError("diagnostic_intent_result_invalid")
    if process.reason == "diagnostic_intent_stream_invalid" and error is None:
        raise _IssuerError("diagnostic_intent_result_invalid")
    return {
        "schema": "simnow.c01.stage-intent-trace.v1",
        "status": "complete"
        if error is None and records
        else ("invalid_stream" if error else "missing"),
        "error": error,
        "record_count": len(records),
        "records": records,
    }


def _audit_document(
    owner: ModuleType,
    helpers: Mapping[str, Any],
    paths: Any,
    *,
    status: str,
    reason: str,
    config_sha256: str = "",
    projection_sha256: str = "",
    selected_index: Any = None,
    account_scope_sha256: str = "",
    credential_binding_sha256: str = "",
    process: Any = None,
    artifacts: Mapping[str, bytes] | None = None,
    validation: Any = None,
    worker_progress: Mapping[str, Any] | None = None,
    fresh_pair_selection: Mapping[str, Any] | None = None,
    pair_binding: Any = None,
    admission: _C01V19Admission | None = None,
) -> dict[str, Any]:
    if type(status) is not str or status not in {"BLOCKED", "CANDIDATE_EVIDENCE_COMPLETE"}:
        raise _IssuerError("issuer_audit_status_invalid")
    owner_pins = dict(owner._SOURCE_PINS)
    selection_value = _validate_fresh_pair_selection(fresh_pair_selection)
    if process is not None and selection_value is None:
        raise _IssuerError("issuer_audit_fresh_pair_selection_missing")
    if pair_binding is not None:
        protocol = helpers["protocol"]
        if (
            type(pair_binding) is not protocol.C01PairBinding
            or selection_value is None
            or pair_binding.selection_sha256 != selection_value["observation_binding_sha256"]
            or (selected_index is not None and pair_binding.selected_index != selected_index)
        ):
            raise _IssuerError("issuer_audit_pair_binding_invalid")
    result: dict[str, Any] = {
        "schema": "simnow.c01.native_td_read_v19.issuer_audit.v1",
        "profile": PROFILE_ID,
        "case_id": CASE_ID,
        "profile_contract_sha256": PROFILE_CONTRACT_SHA256,
        "profile_status": status,
        "reason": reason if _SAFE_REASON.fullmatch(reason) else "issuer_internal_error",
        "private_run_root": str(paths.root.path),
        "consumer_executable": str(Path(sys.executable).resolve()),
        "entry_source_sha256": globals().get("__c01_source_sha256__", ""),
        "source_bindings": {
            "source_manifest_sha256": _SOURCE_MANIFEST_SHA256,
            "owner_sha256": _OWNER_SHA256,
            "worker_sha256": _WORKER_SHA256,
            "case_contract_sha256": _CASE_CONTRACT_SHA256,
            "case_strategy_sha256": _CASE_STRATEGY_SHA256,
            "envref_template_sha256": _ENVREF_TEMPLATE_SHA256,
            "pinned_sources": owner_pins,
        },
        "config_sha256": config_sha256,
        "public_projection_sha256": projection_sha256,
        "selected_index": selected_index,
        "account_scope_sha256": account_scope_sha256,
        "credential_binding_sha256": credential_binding_sha256,
        "write_counters": {"ReqOrderInsert": 0, "ReqOrderAction": 0},
        "diagnostic_stage_intents": None,
    }
    if admission is not None:
        if (
            type(admission) is not _C01V19Admission
            or not _SHA256_RE.fullmatch(admission.admission_sha256)
            or not _SHA256_RE.fullmatch(admission.claim_sha256)
            or not _SHA256_RE.fullmatch(admission.consumed_sha256)
        ):
            raise _IssuerError("issuer_audit_admission_invalid")
        result["protected_admission"] = {
            "schema": _ADMISSION_SCHEMA,
            "profile_id": PROFILE_ID,
            "case_id": CASE_ID,
            "admission_id": admission.admission_id,
            "configured_front_pair_count": admission.configured_front_pair_count,
            "admission_sha256": admission.admission_sha256,
            "claim_sha256": admission.claim_sha256,
            "consumed_sha256": admission.consumed_sha256,
            "bindings_sha256": _canonical_digest(dict(admission.bindings)),
            "source_manifest_sha256": _SOURCE_MANIFEST_SHA256,
        }
    if process is not None:
        protocol = helpers["protocol"]
        supervisor = helpers["supervisor"]
        if type(process) is not supervisor.C01SupervisorResult:
            raise _IssuerError("issuer_audit_supervisor_type_invalid")
        worker_receipt = process.worker_receipt
        lifecycle = process.process_lifecycle
        if type(lifecycle) is not protocol.C01ProcessLifecycleReceipt:
            raise _IssuerError("issuer_audit_lifecycle_type_invalid")
        result["diagnostic_stage_intents"] = _diagnostic_stage_intents_document(
            helpers, process, pair_binding
        )
        lifecycle_value = asdict(lifecycle)
        if type(worker_receipt) is protocol.C01WorkerReceipt:
            try:
                worker_frame = protocol.encode_worker_frame(worker_receipt.to_dict())
                worker_value = protocol.parse_worker_frame(worker_frame).to_dict()
            except Exception:
                raise _IssuerError("issuer_audit_worker_receipt_invalid") from None
            pair_value = worker_value.get("pair_binding")
            if (
                selection_value is None
                or type(pair_value) is not dict
                or pair_value.get("selection_sha256")
                != selection_value["observation_binding_sha256"]
            ):
                raise _IssuerError("issuer_audit_fresh_pair_binding_mismatch")
            worker_digest = _canonical_digest(worker_value)
        elif worker_receipt is None and status == "BLOCKED":
            worker_value = None
            worker_digest = None
        else:
            raise _IssuerError("issuer_audit_worker_receipt_type_invalid")
        result["worker_receipt"] = {
            "type": "C01WorkerReceipt",
            "sha256": worker_digest,
            "value": worker_value,
        }
        result["supervisor_result"] = {
            "type": "C01SupervisorResult",
            "status": process.status,
            "reason": process.reason,
        }
        result["process_lifecycle"] = {
            "type": "C01ProcessLifecycleReceipt",
            "sha256": _canonical_digest(lifecycle_value),
            "value": lifecycle_value,
            "job_active_count": lifecycle.job_active_count,
            "process_exit_code": lifecycle.process_exit_code,
            "stdout_eof": lifecycle.stdout_eof,
            "stderr_eof": lifecycle.stderr_eof,
            "handles_closed": lifecycle.handles_closed,
        }
    if artifacts is not None:
        result["snapshots"] = {
            name: hashlib.sha256(payload).hexdigest() for name, payload in sorted(artifacts.items())
        }
    if worker_progress is not None:
        result["worker_progress"] = _safe_progress_summary(worker_progress)
    if selection_value is not None:
        result["fresh_pair_selection"] = selection_value
    if validation is not None:
        validation_value = {
            "eligible_for_protected_admission": validation.eligible_for_protected_admission,
            "status": validation.status,
            "reasons": list(validation.reasons),
            "checked_request_count": validation.checked_request_count,
            "checked_query_callback_count": validation.checked_query_callback_count,
            "checked_snapshot_count": validation.checked_snapshot_count,
        }
        result["validation"] = {
            "type": "C01CandidateValidation",
            "sha256": _canonical_digest(validation_value),
            **validation_value,
        }
    return result


def _persist_private_audit(
    paths: Any, helpers: Mapping[str, Any], document: Mapping[str, Any]
) -> str:
    try:
        encoded = json.dumps(
            document,
            ensure_ascii=True,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("ascii")
        if len(encoded) > MAX_PRIVATE_AUDIT_BYTES:
            raise _IssuerError("issuer_audit_size_invalid")
        digest = paths.root.write_json("issuer-audit.json", dict(document))
        audit_path = paths.root.path / "issuer-audit.json"
        private = helpers["private"]
        r3_cli = helpers["r3_cli"]
        api = private._api()
        sid = api.current_sid()
        with r3_cli._locked_readonly_file(audit_path, private, api) as (handle, _identity):
            api.verify_acl(handle, sid, directory=False)
            raw = r3_cli._read_bounded_handle(api, handle, MAX_PRIVATE_AUDIT_BYTES)
        if hashlib.sha256(raw).hexdigest() != digest:
            raise _IssuerError("issuer_audit_digest_mismatch")
        paths.root.verify()
        return digest
    except _IssuerError:
        raise
    except Exception:
        raise _IssuerError("issuer_audit_persist_failed") from None


def _run_candidate(
    owner: ModuleType,
    helpers: Mapping[str, Any],
    *,
    deadline: float,
    admission: _C01V19Admission,
    worker_observation_sink: dict[str, Any],
    post_worker_failure_sink: dict[str, Any],
) -> str:
    protocol = helpers["protocol"]
    supervisor = helpers["supervisor"]
    contract = helpers["contract"]
    root = owner._repo_root()
    private_paths = None
    audit_state: dict[str, Any] = {
        "status": "BLOCKED",
        "reason": "candidate_incomplete",
    }
    try:
        if type(admission) is not _C01V19Admission or not admission.active():
            raise _IssuerError("admission_expired_during_run")
        with ExitStack() as stack:
            front_pairs, config_digest, verify_config = stack.enter_context(
                _private_pair_config_lease(root, helpers)
            )
            _validate_admitted_front_pair_count(admission, front_pairs)
            if config_digest != admission.bindings.get("config_source_sha256"):
                raise _IssuerError("admission_config_binding_mismatch")
            if not admission.active():
                raise _IssuerError("admission_expired_during_run")
            required_after_selection = (
                MAX_RUN_SECONDS + MAX_CLEANUP_SECONDS + MAX_POST_RUN_VALIDATION_SECONDS
            )
            if deadline - time.monotonic() < required_after_selection:
                raise _IssuerError("issuer_deadline_reserve_unavailable")
            selection_deadline = min(
                time.monotonic() + MAX_PAIR_SELECTION_SECONDS,
                deadline - required_after_selection,
            )
            projection = _pair_projection(helpers, front_pairs)
            projection_sha256 = hashlib.sha256(projection).hexdigest()
            pair_binding = _select_current_pair(
                helpers,
                front_pairs,
                deadline=selection_deadline,
                audit_sink=audit_state,
            )
            selected_pair = _selected_pair_from_binding(
                helpers,
                front_pairs,
                pair_binding,
                expected_projection_sha256=projection_sha256,
            )
            audit_state.update(
                config_sha256=config_digest,
                projection_sha256=projection_sha256,
                selected_index=pair_binding.selected_index,
                pair_binding=pair_binding,
            )
            verify_config()
            _validate_admitted_front_pair_count(admission, front_pairs)
            if config_digest != admission.bindings.get("config_source_sha256"):
                raise _IssuerError("admission_config_binding_mismatch")
            if not admission.active():
                raise _IssuerError("admission_expired_during_run")
            if deadline - time.monotonic() < required_after_selection:
                raise _IssuerError("issuer_deadline_reserve_unavailable")
            credentials = stack.enter_context(
                _credential_lease(
                    owner,
                    root,
                    helpers,
                    front_pairs,
                    pair_binding,
                    expected_projection_sha256=projection_sha256,
                )
            )
            if not admission.active():
                raise _IssuerError("admission_expired_during_run")
            if deadline - time.monotonic() < required_after_selection:
                raise _IssuerError("issuer_deadline_reserve_unavailable")
            private_paths = stack.enter_context(owner._private_run(helpers))
            audit_state["private_run_root"] = str(private_paths.root.path)
            verify_config()
            packet, account_digest, credential_digest = owner._private_input_packet(
                helpers, credentials, private_paths
            )
            if account_digest != admission.bindings.get(
                "account_scope_sha256"
            ) or credential_digest != admission.bindings.get("credential_binding_sha256"):
                raise _IssuerError("admission_account_binding_mismatch")
            audit_state.update(
                account_scope_sha256=account_digest,
                credential_binding_sha256=credential_digest,
            )
            if deadline - time.monotonic() < required_after_selection:
                raise _IssuerError("issuer_deadline_exceeded")
            if not admission.active():
                raise _IssuerError("admission_expired_during_run")
            _validate_fresh_pair_selection(
                audit_state.get("fresh_pair_selection"),
                expected_selection_sha256=pair_binding.selection_sha256,
            )
            worker_path = root / "backtrader_runtime" / "certification_simnow_c01_native_v4.py"
            try:
                process = supervisor.run_fixed_c01_worker(
                    worker_path=worker_path,
                    source_root=worker_path.parent,
                    expected_worker_source_sha256=_WORKER_SHA256,
                    pair_binding=pair_binding,
                    account_scope_sha256=account_digest,
                    credential_binding_sha256=credential_digest,
                    credential_packet=packet,
                    timeout_seconds=MAX_RUN_SECONDS,
                    cleanup_seconds=MAX_CLEANUP_SECONDS,
                    diagnostic_intents=_DIAGNOSTIC_INTENTS_ONLY,
                )
            except Exception:
                raise _IssuerError("worker_supervisor_failed") from None
            audit_state["process"] = process
            if type(process) is supervisor.C01SupervisorResult:
                audit_state["worker_progress"] = _read_worker_progress(
                    owner,
                    helpers,
                    private_paths,
                    process,
                    pair_binding,
                    account_digest,
                    credential_digest,
                )
            else:
                audit_state["worker_progress"] = _empty_progress_summary("unavailable")
            failure_diagnostic = _read_worker_failure_diagnostic(
                owner,
                helpers,
                private_paths,
                process,
                pair_binding,
                account_digest,
                credential_digest,
                deadline=deadline,
            )
            observation = _project_worker_observation(
                helpers,
                process,
                audit_state["worker_progress"],
                failure_diagnostic,
            )
            if observation is not None:
                worker_observation_sink["value"] = observation
            if type(process) is not supervisor.C01SupervisorResult:
                raise _IssuerError("worker_process_incomplete")
            if not admission.active():
                raise _IssuerError("admission_expired_during_run")
            if not owner._worker_process_complete(helpers, process):
                lifecycle = getattr(process, "process_lifecycle", None)
                if getattr(lifecycle, "timed_out", False):
                    raise _IssuerError("native_close_unknown")
                raise _IssuerError("worker_process_incomplete")
            if process.reason == "diagnostic_profile_only":
                raise _IssuerError("diagnostic_profile_only")
            if process.reason == "diagnostic_intent_stream_invalid":
                raise _IssuerError("diagnostic_intent_stream_invalid")
            progress = audit_state["worker_progress"]
            if (
                progress.get("status") != "verified"
                or progress.get("last_stage") != "worker_receipt"
                or progress.get("last_event") != "end"
            ):
                raise _IssuerError("worker_progress_invalid")
            if time.monotonic() >= deadline:
                raise _IssuerError("issuer_deadline_exceeded")
            if not owner._worker_receipt_matches(
                helpers, process, pair_binding, account_digest, credential_digest
            ):
                raise _IssuerError("worker_receipt_misbinding")
            verify_config()
            try:
                owner._verify_tree(helpers, private_paths, expected_snapshots=True)
            except Exception as error:
                if type(error) is owner._OwnerError:
                    post_worker_failure_sink["stage"] = "verify_tree"
                    post_worker_failure_sink["code"] = _owner_failure_code(
                        owner, error, "verify_tree"
                    )
                    raise _IssuerError("candidate_owner_validation_failed") from None
                raise
            try:
                artifacts = owner._read_snapshot_artifacts(helpers, private_paths)
            except Exception as error:
                if type(error) is owner._OwnerError:
                    post_worker_failure_sink["stage"] = "read_snapshot_artifacts"
                    post_worker_failure_sink["code"] = _owner_failure_code(
                        owner, error, "read_snapshot_artifacts"
                    )
                    raise _IssuerError("candidate_owner_validation_failed") from None
                raise
            audit_state["artifacts"] = artifacts
            if deadline - time.monotonic() < 0:
                raise _IssuerError("issuer_deadline_exceeded")
            try:
                decision = contract.validate_c01_candidate(
                    process.worker_receipt,
                    process.process_lifecycle,
                    expected_pair_binding=pair_binding,
                    expected_worker_source_sha256=_WORKER_SHA256,
                    expected_account_scope_sha256=account_digest,
                    expected_credential_binding_sha256=credential_digest,
                    private_snapshot_artifacts=artifacts,
                    expected_broker_id=credentials.broker_id,
                    expected_user_id=credentials.user_id,
                )
            except Exception:
                raise _IssuerError("candidate_contract_failed") from None
            audit_state["validation"] = decision
            if deadline - time.monotonic() < 0:
                raise _IssuerError("issuer_deadline_exceeded")
            if not _validation_issues_pass(contract, protocol, decision):
                raise _IssuerError("candidate_contract_ineligible")
            if not admission.active():
                raise _IssuerError("admission_expired_during_run")
        audit_state.update(
            status="CANDIDATE_EVIDENCE_COMPLETE", reason="read_only_candidate_complete"
        )
    except _IssuerError as error:
        audit_state.update(
            status="BLOCKED",
            reason=error.args[0] if error.args else "candidate_incomplete",
        )
        if private_paths is not None:
            try:
                _persist_private_audit(
                    private_paths,
                    helpers,
                    _audit_document(
                        owner,
                        helpers,
                        private_paths,
                        status=audit_state["status"],
                        reason=audit_state["reason"],
                        config_sha256=audit_state.get("config_sha256", ""),
                        projection_sha256=audit_state.get("projection_sha256", ""),
                        selected_index=audit_state.get("selected_index"),
                        account_scope_sha256=audit_state.get("account_scope_sha256", ""),
                        credential_binding_sha256=audit_state.get("credential_binding_sha256", ""),
                        process=audit_state.get("process"),
                        artifacts=audit_state.get("artifacts"),
                        validation=audit_state.get("validation"),
                        worker_progress=audit_state.get("worker_progress"),
                        fresh_pair_selection=audit_state.get("fresh_pair_selection"),
                        pair_binding=audit_state.get("pair_binding"),
                        admission=admission,
                    ),
                )
            except Exception:
                pass
        raise
    except Exception:
        audit_state.update(status="BLOCKED", reason="candidate_internal_error")
        if private_paths is not None:
            try:
                _persist_private_audit(
                    private_paths,
                    helpers,
                    _audit_document(
                        owner,
                        helpers,
                        private_paths,
                        status="BLOCKED",
                        reason="candidate_internal_error",
                        config_sha256=audit_state.get("config_sha256", ""),
                        projection_sha256=audit_state.get("projection_sha256", ""),
                        selected_index=audit_state.get("selected_index"),
                        account_scope_sha256=audit_state.get("account_scope_sha256", ""),
                        credential_binding_sha256=audit_state.get("credential_binding_sha256", ""),
                        process=audit_state.get("process"),
                        artifacts=audit_state.get("artifacts"),
                        validation=audit_state.get("validation"),
                        worker_progress=audit_state.get("worker_progress"),
                        fresh_pair_selection=audit_state.get("fresh_pair_selection"),
                        pair_binding=audit_state.get("pair_binding"),
                        admission=admission,
                    ),
                )
            except Exception:
                pass
        raise _IssuerError("candidate_internal_error") from None

    if private_paths is None:
        raise _IssuerError("private_run_root_missing")
    try:
        _persist_private_audit(
            private_paths,
            helpers,
            _audit_document(
                owner,
                helpers,
                private_paths,
                status="CANDIDATE_EVIDENCE_COMPLETE",
                reason="read_only_candidate_complete",
                config_sha256=audit_state["config_sha256"],
                projection_sha256=audit_state["projection_sha256"],
                selected_index=audit_state["selected_index"],
                account_scope_sha256=audit_state["account_scope_sha256"],
                credential_binding_sha256=audit_state["credential_binding_sha256"],
                process=audit_state["process"],
                artifacts=audit_state["artifacts"],
                validation=audit_state["validation"],
                worker_progress=audit_state.get("worker_progress"),
                fresh_pair_selection=audit_state.get("fresh_pair_selection"),
                pair_binding=audit_state.get("pair_binding"),
                admission=admission,
            ),
        )
    except _IssuerError:
        raise _IssuerError("issuer_audit_persist_failed") from None
    return "read_only_candidate_complete"


def _validate_admitted_front_pair_count(
    admission: _C01V19Admission, front_pairs: Sequence[Mapping[str, str]]
) -> None:
    if (
        type(admission) is not _C01V19Admission
        or type(admission.configured_front_pair_count) is not int
        or not 1 <= admission.configured_front_pair_count <= 8
    ):
        raise _IssuerError("admission_binding_mismatch")
    if type(front_pairs) not in (tuple, list) or not 1 <= len(front_pairs) <= 8:
        raise _IssuerError("configured_front_pair_count_invalid")
    if len(front_pairs) != admission.configured_front_pair_count:
        raise _IssuerError("admission_front_pair_count_mismatch")


def run_c01_native_td_read_v19() -> C01NativeTdReadV19Result:
    """Run the explicit C01 native TD read profile in this current process.

    No inputs are accepted from a caller.  Every successful decision is based
    on a fresh pinned worker invocation, parent-observed Windows Job facts,
    owner-only current artifacts, and frozen contract recomputation.
    """

    if not _ISSUER_LOCK.acquire(blocking=False):
        return _blocked("issuer_already_running")
    owner = None
    worker_observation_sink: dict[str, Any] = {"value": None}
    post_worker_failure_sink: dict[str, Any] = {"stage": "none", "code": "none"}
    started = time.monotonic()
    deadline = started + MAX_PROFILE_SECONDS
    try:
        if not _SHA256_RE.fullmatch(globals().get("__c01_source_sha256__", "")):
            return _blocked("fixed_source_bootstrap_required")
        root = _repo_root()
        issuer_module = sys.modules.get(__name__)
        if issuer_module is None or issuer_module.__dict__ is not globals():
            raise _IssuerError("fixed_source_bootstrap_required")
        with _profile_admission_lease(root, issuer_module) as admission:
            # The one-shot registration is durable before environment,
            # interpreter, profile, worker, SDK, config, or credential reads.
            _require_clean_ambient_secrets()
            if not admission.active():
                raise _IssuerError("admission_expired_during_run")
            if not _consumer_matches():
                raise _IssuerError("approved_cpython311_consumer_required")
            _verify_public_profile_sources(root)
            owner = _load_frozen_owner(root)
            _verify_source_manifest(root, owner)
            with owner._verified_helper_bundle() as helpers:
                helpers = dict(helpers)
                helpers["owner_now_utc"] = owner._now_utc
                if time.monotonic() >= deadline:
                    raise _IssuerError("issuer_deadline_exceeded")
                reason = _run_candidate(
                    owner,
                    helpers,
                    deadline=deadline,
                    admission=admission,
                    worker_observation_sink=worker_observation_sink,
                    post_worker_failure_sink=post_worker_failure_sink,
                )
                if reason != "read_only_candidate_complete":
                    raise _IssuerError("candidate_contract_ineligible")
                if not admission.active():
                    raise _IssuerError("admission_expired_during_run")
        return C01NativeTdReadV19Result(
            "PASS",
            "read_only_candidate_complete",
            worker_observation=worker_observation_sink["value"],
            post_worker_failure_stage=post_worker_failure_sink["stage"],
            post_worker_failure_code=post_worker_failure_sink["code"],
            _factory=_RESULT_FACTORY,
        )
    except _IssuerError as error:
        if type(error) is _AdmissionLeaseFailure:
            return _blocked(
                error.args[0] if error.args else "issuer_blocked",
                admission_failure_stage=error.stage,
                admission_failure_class=error.failure_class,
                worker_observation=worker_observation_sink["value"],
                post_worker_failure_stage=post_worker_failure_sink["stage"],
                post_worker_failure_code=post_worker_failure_sink["code"],
            )
        return _blocked(
            error.args[0] if error.args else "issuer_blocked",
            worker_observation=worker_observation_sink["value"],
            post_worker_failure_stage=post_worker_failure_sink["stage"],
            post_worker_failure_code=post_worker_failure_sink["code"],
        )
    except Exception:
        return _blocked(
            "issuer_internal_error",
            worker_observation=worker_observation_sink["value"],
            post_worker_failure_stage=post_worker_failure_sink["stage"],
            post_worker_failure_code=post_worker_failure_sink["code"],
        )
    finally:
        if owner is not None and sys.modules.get(_OWNER_MODULE_NAME) is owner:
            sys.modules.pop(_OWNER_MODULE_NAME, None)
        _ISSUER_LOCK.release()


__all__ = [
    "CASE_ID",
    "PROFILE_CONTRACT_SHA256",
    "PROFILE_ID",
    "C01NativeTdReadV19Result",
    "run_c01_native_td_read_v19",
]
