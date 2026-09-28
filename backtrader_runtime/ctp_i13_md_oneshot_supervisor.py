"""Unregistered I13 one-shot MD diagnostic under a Windows Job supervisor.

This candidate is separate from the runtime inventory. It reuses the sealed
013_3 configuration/front binding, the installed-artifact verifier, the
existing MD callback adapter, and the bounded Job supervisor. Completion
requires a verified login identity, one adapter-accepted same-TradingDay tick,
the SDK's independent value-free receipt, and confirmed native close evidence.
It has no TD, settlement, order, cancel, or write call path.
"""

from __future__ import annotations

import ctypes
import hashlib
import importlib
import json
import logging
import math
import os
import stat
import sys
import threading
import time
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Mapping, Optional, Sequence

from .ctp_i12_td_only_readonly import (
    I12FrontPrecheckBinding,
    _I12_PRECHECK_BINDING_ENV,
    _I12_PRECHECK_INDEX_ENV,
    _parent_credential_free_precheck,
)
from .ctp_i13_md_observability import (
    I13EventKind,
    I13MdEvent,
    merge_i13_md_diagnostic_receipt,
)
from .ctp_readonly_job_supervisor import (
    FailClosedLatch,
    FixedChildCommand,
    ProcessEvidence,
    SupervisedResult,
    ValueFreeReceiptSchema,
    parse_single_json_receipt,
    run_readonly_child,
)
from .ctp_i13_source_identity import (
    I13SourceIdentityError,
    I13SourceLease,
    acquire_i13_source_lease,
    verify_i13_source_identity,
    verify_i13_runtime_import_origins,
)
from .ctp_i13_source_identity_pin import I13_SOURCE_MANIFEST_SHA256
from .inventory import (
    ITERATION41_013_3_CTP_PRIVATE_RUNTIME_DIR,
    ITERATION41_013_3_CTP_PRIVATE_RUNTIME_ID,
    iteration41_runtime_registry,
)
from .registry import require_effective_runtime_config_seal, validate_runtime_config


I13_SDK_SOURCE_COMMIT = "c68bebe8631419801e7a24e13b98c42867df0beb"
I13_CTP_WHEEL_SHA256 = "c6eb83c1389b8f0e96edf9f727c20901b2411961489e19abb4ee1aef6ec2ce5d"
_I13_RUNTIME_ROOT = Path(r"D:\temp\i13-final-wheel-repro-20260925\venv")
_I13_INTERPRETER = _I13_RUNTIME_ROOT / "Scripts" / "python.exe"
_I13_EVIDENCE_ROOT = Path(r"D:\temp\i13-final-wheel-repro-20260925")
_I13_BASE_PYTHON_ROOT = Path(r"C:\anaconda3")
_I13_JOB_HANDLE_ENV = "bt_i13_parent_job_handle"
_I13_DEADLINE_ENV = "bt_i13_parent_deadline_monotonic"
_I13_SOURCE_MANIFEST_ENV = "bt_i13_source_manifest_sha256"
_I13_PYCACHE_PREFIX_ENV = "bt_i13_pycache_prefix"
_I13_MARKER_CONTENT = b"i13-md-oneshot-supervisor-attempted-v1\n"
I13_LATCH_PATH = (
    ITERATION41_013_3_CTP_PRIVATE_RUNTIME_DIR / "state" / "i13-md-oneshot-supervisor-no-retry.latch"
)
_I13_TOTAL_DEADLINE_SECONDS = 90.0
_I13_TERMINATION_GRACE_SECONDS = 5.0
_I13_MAX_STDOUT_BYTES = 24 * 1024
_I13_ARTIFACT_PREFLIGHT_SECONDS = 10.0
_I13_MARKET_OBSERVATION_SECONDS = 15.0
_I13_RETAINED_JOB_CONTROL: Optional[object] = None
_I13_RETAINED_SOURCE_LEASE: Optional[I13SourceLease] = None

_I13_STATUSES = ("diagnostic_complete", "incomplete", "rejected")
_I13_REASONS = (
    "adapter_observation_incomplete",
    "arguments_not_allowed",
    "child_deadline_exceeded",
    "child_diagnostic_rejected",
    "child_process_exited",
    "configuration_rejected",
    "credential_rejected",
    "front_precheck_failed",
    "i13_latch_unavailable",
    "i13_runtime_unavailable",
    "i13_supervisor_failed",
    "i13_supervisor_result_invalid",
    "identity_unverified",
    "invalid_child_receipt",
    "market_probe_failed",
    "matching_tick_observed",
    "native_join_pending",
    "parent_completion_evidence_missing",
    "prior_attempt_or_poisoned_latch",
    "runtime_policy_rejected",
    "sdk_artifact_rejected",
    "sdk_receipt_invalid",
    "source_identity_unverified",
    "supervisor_context_required",
    "windows_required",
    "stdout_limit_exceeded",
)
_I13_STAGES = (
    "arguments",
    "configuration",
    "credentials",
    "front_selection",
    "market_data",
    "sdk_artifact",
)
_I13_CLOSE_STATES = (
    "not_attempted",
    "verified_closed",
    "native_join_pending",
    "stop_returned",
    "unknown",
)
_I13_BOOL_COUNT_VALUES = ("zero", "one", "multiple", "unknown")
_I13_IDENTITY_VALUES = ("verified", "identity_unverified", "unavailable")

I13_CHILD_RECEIPT_SCHEMA = ValueFreeReceiptSchema(
    enum_fields={
        "adapter_ack_tick_order": (
            "ack_before_all_ticks",
            "ack_between_ticks",
            "ack_without_tick",
            "neither_observed",
            "tick_before_ack",
            "tick_without_ack",
            "unknown",
        ),
        "adapter_acknowledgement_state": (
            "acknowledged",
            "not_observed_at_window_close",
            "unknown",
        ),
        "adapter_accepted_tick_count": _I13_BOOL_COUNT_VALUES,
        "adapter_tick_arrival_count": _I13_BOOL_COUNT_VALUES,
        "adapter_evidence_integrity": ("valid", "invalid"),
        "adapter_login_identity_state": _I13_IDENTITY_VALUES,
        "adapter_native_join_state": (
            "completed",
            "completed_after_pending",
            "evidence_inconsistent",
            "pending_observed",
            "unknown",
        ),
        "adapter_primary_probe_reason": (
            "matching_tick_observed",
            "market_front_disconnected",
            "market_identity_unverified",
            "market_login_timeout",
            "market_observation_incomplete",
            "market_probe_failed",
            "market_subscription_rejected",
            "probe_deadline_expired",
            "unknown",
        ),
        "adapter_tick_classification": (
            "adapter_rejected",
            "evidence_inconsistent",
            "no_tick_observed",
            "sdk_rejected",
            "tick_accepted",
            "tick_arrived_unclassified",
            "unknown",
        ),
        "close_state": _I13_CLOSE_STATES,
        "diagnostic_id": ("i13_oneshot_md_diagnostic",),
        "reason": _I13_REASONS,
        "sdk_broker_id_shape": ("exact_match", "empty", "other", "not_observed", "unknown"),
        "sdk_evidence_integrity": ("valid", "invalid"),
        "sdk_login_callback_count": _I13_BOOL_COUNT_VALUES,
        "sdk_login_disposition": ("accepted", "identity_unverified", "none", "other", "unknown"),
        "sdk_native_broker_id_shape": (
            "nonempty_terminated",
            "empty",
            "other",
            "not_observed",
            "unknown",
        ),
        "sdk_native_user_id_shape": (
            "nonempty_terminated",
            "empty",
            "other",
            "not_observed",
            "unknown",
        ),
        "sdk_receipt_terminal_state": ("complete", "other", "not_terminal", "unknown"),
        "sdk_request_id_relation": ("zero", "not_observed", "other", "unknown"),
        "sdk_response_error_status": ("zero", "not_observed", "other", "unknown"),
        "sdk_subscription_error_status": ("zero", "not_observed", "other", "unknown"),
        "sdk_trading_day_shape": ("valid", "empty", "not_observed", "other", "unknown"),
        "sdk_user_id_shape": ("exact_match", "empty", "other", "not_observed", "unknown"),
        "stage": _I13_STAGES,
        "status": _I13_STATUSES,
        "selected_pair_index": ("unavailable",) + tuple(f"pair_{index}" for index in range(8)),
    },
    nullable_enum_fields={},
    bool_fields=(
        "credential_resolver_invoked",
        "parent_precheck_binding_match",
        "order_submission_authorized",
        "sdk_imported",
        "sdk_receipt_observed",
        "sdk_subscription_submitted",
        "settlement_writes_zero",
        "source_identity_verified",
        "trading_ready",
        "trading_writes_zero",
    ),
    nullable_bool_fields=(
        "adapter_same_trading_day_observed",
        "client_stop_returned",
        "native_join_pending",
        "probe_session_closed",
        "sdk_first_tick_pending",
        "sdk_first_tick_received",
        "sdk_subscription_acknowledged",
    ),
)

_I13_ARTIFACT_PREFLIGHT_SCHEMA = ValueFreeReceiptSchema(
    enum_fields={
        "reason": ("artifact_rejected", "artifact_verified"),
        "status": ("rejected", "verified"),
    },
    nullable_enum_fields={},
    bool_fields=(
        "credential_resolver_invoked",
        "native_join_pending",
        "sdk_imported",
        "source_identity_verified",
    ),
)


@dataclass(frozen=True)
class I13DiagnosticReport:
    """Safe parent summary; the child receipt and OS evidence stay separate."""

    status: str
    reason: str
    attempt_reserved: bool
    selected_pair_index: Optional[int]
    artifact_pin_verified: Optional[bool]
    artifact_job_containment: str
    supervised: Optional[SupervisedResult]
    source_identity_manifest_sha256: Optional[str] = None

    def as_public_dict(self) -> dict[str, object]:
        result = self.supervised
        evidence = _empty_evidence("not_started") if result is None else result.process_evidence
        receipt = None if result is None else _exact_i13_child_receipt(result.sdk_receipt)
        return {
            "diagnostic_id": "i13_oneshot_md_diagnostic",
            "adapter_close_evidence": _adapter_close_view(receipt),
            "adapter_observability": _adapter_observability_view(receipt),
            "artifact_pin_precheck": {
                "job_containment": self.artifact_job_containment
                if self.artifact_job_containment
                in {"not_started", "unavailable", "uncertain", "verified"}
                else "unavailable",
                "verified": self.artifact_pin_verified
                if type(self.artifact_pin_verified) is bool
                else None,
            },
            "attempt_reserved": self.attempt_reserved is True,
            "process_evidence": _safe_process_evidence(evidence),
            "reason": self.reason if self.reason in _I13_REASONS else "i13_supervisor_failed",
            "diagnostic_receipt": _sdk_diagnostic_view(receipt),
            "selected_pair_index": (
                f"pair_{self.selected_pair_index}"
                if type(self.selected_pair_index) is int and 0 <= self.selected_pair_index < 8
                else "unavailable"
            ),
            "status": self.status
            if self.status
            in {"diagnostic_complete", "incomplete", "latched", "rejected", "supervisor_error"}
            else "supervisor_error",
            "scope": "unregistered_programmatic_candidate",
            "source_identity": {
                "bound": self.source_identity_manifest_sha256 == I13_SOURCE_MANIFEST_SHA256,
                "manifest_sha256": self.source_identity_manifest_sha256
                if self.source_identity_manifest_sha256 == I13_SOURCE_MANIFEST_SHA256
                else None,
                "status": "pinned_source_tree_verified"
                if self.source_identity_manifest_sha256 == I13_SOURCE_MANIFEST_SHA256
                else "current_checkout_source_unsealed",
            },
        }


def _sdk_diagnostic_view(receipt: Optional[Mapping[str, object]]) -> Optional[dict[str, object]]:
    if receipt is None:
        return None
    return {key: value for key, value in receipt.items() if key.startswith("sdk_")}


def _adapter_observability_view(
    receipt: Optional[Mapping[str, object]],
) -> Optional[dict[str, object]]:
    if receipt is None:
        return None
    return {key: value for key, value in receipt.items() if key.startswith("adapter_")}


def _adapter_close_view(receipt: Optional[Mapping[str, object]]) -> Optional[dict[str, object]]:
    if receipt is None:
        return None
    return {
        key: receipt[key]
        for key in (
            "client_stop_returned",
            "close_state",
            "native_join_pending",
            "probe_session_closed",
        )
    }


def _empty_evidence(containment: str) -> ProcessEvidence:
    return ProcessEvidence(False, False, False, None, None, False, None, None, containment)


def _safe_process_evidence(value: object) -> dict[str, object]:
    evidence = value if type(value) is ProcessEvidence else _empty_evidence("unavailable")
    return {
        "containment": evidence.containment
        if evidence.containment
        in {"latched", "not_started", "unavailable", "uncertain", "verified"}
        else "unavailable",
        "job_assignment_observed": evidence.job_assignment_observed is True,
        "job_empty_observed": evidence.job_empty_observed
        if type(evidence.job_empty_observed) is bool
        else None,
        "job_termination_call_succeeded": evidence.job_termination_call_succeeded
        if type(evidence.job_termination_call_succeeded) is bool
        else None,
        "job_termination_requested": evidence.job_termination_requested is True,
        "process_created": evidence.process_created is True,
        "process_exit_code": evidence.process_exit_code
        if type(evidence.process_exit_code) is int
        else None,
        "process_exit_observed": evidence.process_exit_observed
        if type(evidence.process_exit_observed) is bool
        else None,
        "process_resumed": evidence.process_resumed is True,
    }


def _count_bucket(value: object) -> str:
    if type(value) is not int or value < 0:
        return "unknown"
    if value == 0:
        return "zero"
    return "one" if value == 1 else "multiple"


def _safe_enum(value: object, allowed: Sequence[str]) -> str:
    return value if type(value) is str and value in allowed else "unknown"


def _shape(value: object, *, exact: Optional[str] = None, empty: str = "empty") -> str:
    if type(value) is not str:
        return "unknown"
    if value == "not_observed":
        return "not_observed"
    if exact is not None and value == exact:
        return exact
    if value == empty:
        return empty
    return "other"


def _sdk_disposition(value: object) -> str:
    if value in {"accepted", "identity_unverified", "none"}:
        return value
    return "other" if type(value) is str else "unknown"


def _sdk_terminal_state(terminal: object, reason: object) -> str:
    if type(terminal) is not bool:
        return "unknown"
    if terminal is False:
        return "not_terminal"
    return "complete" if reason == "diagnostic_complete" else "other"


def _merge_receipt_fields(
    sdk_receipt: object,
    adapter_events: Sequence[object],
    *,
    observation: object = None,
    progress: object = None,
    close_state: object = "not_attempted",
    client_stop_returned: object = None,
    native_join_pending: object = None,
    probe_session_closed: object = None,
    parent_precheck_binding_match: bool = False,
    credential_resolver_invoked: bool = False,
    sdk_imported: bool = False,
    source_identity_verified: bool = False,
    selected_pair_index: Optional[int] = None,
    status: str = "incomplete",
    reason: str = "adapter_observation_incomplete",
    stage: str = "market_data",
) -> dict[str, object]:
    """Project both channels through the shared pure I13 contract."""

    merged = merge_i13_md_diagnostic_receipt(sdk_receipt, adapter_events)
    public = merged.as_public_dict()
    sdk = public["sdk_receipt"]
    adapter = public["adapter_observability"]
    login_callback = sdk.get("login_callback") if type(sdk) is dict else None
    if type(login_callback) is not dict:
        login_callback = {}

    identity_state = "unavailable"
    adapter_day: Optional[bool] = None
    if observation is not None:
        identity_state = _safe_enum(
            getattr(observation, "login_identity_state", None), _I13_IDENTITY_VALUES
        )
        adapter_day = getattr(observation, "same_trading_day_observed", None)
        client_stop_returned = getattr(observation, "client_stop_returned", client_stop_returned)
        native_join_pending = getattr(observation, "native_join_pending", native_join_pending)
        probe_session_closed = getattr(observation, "probe_session_closed", probe_session_closed)
    elif progress is not None:
        identity_state = _safe_enum(
            getattr(progress, "login_identity_state", None), _I13_IDENTITY_VALUES
        )
        adapter_day = getattr(progress, "same_trading_day_observed", None)

    # The pure I13 projector remains the only source of event consistency and
    # SDK receipt validity decisions. This adapter layer only buckets its
    # already-redacted public projection for the strict child wire schema.
    output = {
        "adapter_ack_tick_order": _safe_enum(
            adapter.get("ack_tick_order"),
            I13_CHILD_RECEIPT_SCHEMA.enum_fields["adapter_ack_tick_order"],
        ),
        "adapter_acknowledgement_state": _safe_enum(
            adapter.get("acknowledgement_state"),
            I13_CHILD_RECEIPT_SCHEMA.enum_fields["adapter_acknowledgement_state"],
        ),
        "adapter_accepted_tick_count": _count_bucket(adapter.get("accepted_tick_count")),
        "adapter_evidence_integrity": _safe_enum(
            adapter.get("evidence_integrity"), ("valid", "invalid")
        ),
        "adapter_login_identity_state": identity_state,
        "adapter_native_join_state": _safe_enum(
            adapter.get("native_join_state"),
            I13_CHILD_RECEIPT_SCHEMA.enum_fields["adapter_native_join_state"],
        ),
        "adapter_primary_probe_reason": _safe_enum(
            adapter.get("primary_probe_reason"),
            I13_CHILD_RECEIPT_SCHEMA.enum_fields["adapter_primary_probe_reason"],
        ),
        "adapter_same_trading_day_observed": adapter_day
        if type(adapter_day) is bool
        else adapter.get("same_trading_day_observed")
        if type(adapter.get("same_trading_day_observed")) is bool
        else None,
        "adapter_tick_arrival_count": _count_bucket(adapter.get("tick_arrival_count")),
        "adapter_tick_classification": _safe_enum(
            adapter.get("tick_classification"),
            I13_CHILD_RECEIPT_SCHEMA.enum_fields["adapter_tick_classification"],
        ),
        "close_state": _safe_enum(close_state, _I13_CLOSE_STATES),
        "client_stop_returned": client_stop_returned
        if type(client_stop_returned) is bool
        else None,
        "credential_resolver_invoked": credential_resolver_invoked is True,
        "diagnostic_id": "i13_oneshot_md_diagnostic",
        "parent_precheck_binding_match": parent_precheck_binding_match is True,
        "native_join_pending": native_join_pending if type(native_join_pending) is bool else None,
        "order_submission_authorized": False,
        "probe_session_closed": probe_session_closed
        if type(probe_session_closed) is bool
        else None,
        "reason": reason if reason in _I13_REASONS else "market_probe_failed",
        "sdk_broker_id_shape": _shape(login_callback.get("broker_id_shape"), exact="exact_match"),
        "sdk_evidence_integrity": _safe_enum(sdk.get("evidence_integrity"), ("valid", "invalid")),
        "sdk_first_tick_pending": sdk.get("first_tick_pending")
        if type(sdk.get("first_tick_pending")) is bool
        else None,
        "sdk_first_tick_received": sdk.get("first_tick_received")
        if type(sdk.get("first_tick_received")) is bool
        else None,
        "sdk_login_callback_count": _count_bucket(login_callback.get("callback_count")),
        "sdk_login_disposition": _sdk_disposition(login_callback.get("disposition")),
        "sdk_native_broker_id_shape": _shape(
            login_callback.get("native_broker_id_shape"), exact="nonempty_terminated"
        ),
        "sdk_native_user_id_shape": _shape(
            login_callback.get("native_user_id_shape"), exact="nonempty_terminated"
        ),
        "sdk_receipt_observed": sdk.get("receipt_observed") is True,
        "sdk_receipt_terminal_state": _sdk_terminal_state(
            sdk.get("terminal"), sdk.get("terminal_reason")
        ),
        "sdk_request_id_relation": "zero"
        if login_callback.get("request_id_relation") == "zero"
        else "not_observed"
        if login_callback.get("request_id_relation") == "not_observed"
        else "other"
        if type(login_callback.get("request_id_relation")) is str
        else "unknown",
        "sdk_response_error_status": "zero"
        if login_callback.get("response_error_status") == "zero"
        else "not_observed"
        if login_callback.get("response_error_status") == "not_observed"
        else "other"
        if type(login_callback.get("response_error_status")) is str
        else "unknown",
        "sdk_subscription_acknowledged": sdk.get("subscription_acknowledged")
        if type(sdk.get("subscription_acknowledged")) is bool
        else None,
        "sdk_subscription_error_status": "zero"
        if sdk.get("subscription_response_error_status") == "zero"
        else "not_observed"
        if sdk.get("subscription_response_error_status") == "not_observed"
        else "other"
        if type(sdk.get("subscription_response_error_status")) is str
        else "unknown",
        "sdk_subscription_submitted": sdk.get("subscription_submitted") is True,
        "sdk_trading_day_shape": _shape(
            login_callback.get("trading_day_shape"), exact="valid", empty="empty"
        ),
        "sdk_user_id_shape": _shape(login_callback.get("user_id_shape"), exact="exact_match"),
        "selected_pair_index": f"pair_{selected_pair_index}"
        if type(selected_pair_index) is int and 0 <= selected_pair_index < 8
        else "unavailable",
        "settlement_writes_zero": True,
        "sdk_imported": sdk_imported is True,
        "source_identity_verified": source_identity_verified is True,
        "stage": stage if stage in _I13_STAGES else "market_data",
        "status": status if status in _I13_STATUSES else "incomplete",
        "trading_ready": False,
        "trading_writes_zero": True,
    }
    return output


def _emit_i13(payload: Mapping[str, object]) -> None:
    try:
        encoded = json.dumps(dict(payload), sort_keys=True, separators=(",", ":"))
    except (TypeError, ValueError, UnicodeError):
        encoded = json.dumps(
            _minimal_i13_receipt("rejected", "sdk_receipt_invalid", "market_data"),
            sort_keys=True,
            separators=(",", ":"),
        )
    sys.stdout.write(encoded + "\n")
    sys.stdout.flush()


def _minimal_i13_receipt(status: str, reason: str, stage: str) -> dict[str, object]:
    return {
        "diagnostic_id": "i13_oneshot_md_diagnostic",
        "adapter_ack_tick_order": "unknown",
        "adapter_acknowledgement_state": "unknown",
        "adapter_accepted_tick_count": "unknown",
        "adapter_evidence_integrity": "invalid",
        "adapter_login_identity_state": "unavailable",
        "adapter_native_join_state": "unknown",
        "adapter_primary_probe_reason": "unknown",
        "adapter_same_trading_day_observed": None,
        "adapter_tick_arrival_count": "unknown",
        "adapter_tick_classification": "unknown",
        "close_state": "unknown",
        "client_stop_returned": None,
        "credential_resolver_invoked": False,
        "parent_precheck_binding_match": False,
        "native_join_pending": None,
        "order_submission_authorized": False,
        "probe_session_closed": None,
        "reason": reason if reason in _I13_REASONS else "market_probe_failed",
        "sdk_broker_id_shape": "unknown",
        "sdk_evidence_integrity": "invalid",
        "sdk_first_tick_pending": None,
        "sdk_first_tick_received": None,
        "sdk_login_callback_count": "unknown",
        "sdk_login_disposition": "unknown",
        "sdk_native_broker_id_shape": "unknown",
        "sdk_native_user_id_shape": "unknown",
        "sdk_receipt_observed": False,
        "sdk_receipt_terminal_state": "unknown",
        "sdk_request_id_relation": "unknown",
        "sdk_response_error_status": "unknown",
        "sdk_subscription_acknowledged": None,
        "sdk_subscription_error_status": "unknown",
        "sdk_subscription_submitted": False,
        "sdk_trading_day_shape": "unknown",
        "sdk_user_id_shape": "unknown",
        "selected_pair_index": "unavailable",
        "settlement_writes_zero": True,
        "sdk_imported": False,
        "source_identity_verified": False,
        "stage": stage if stage in _I13_STAGES else "market_data",
        "status": status if status in _I13_STATUSES else "rejected",
        "trading_ready": False,
        "trading_writes_zero": True,
    }


def parse_i13_child_receipt(raw: bytes) -> Optional[Mapping[str, object]]:
    return parse_single_json_receipt(raw, I13_CHILD_RECEIPT_SCHEMA)


def _exact_i13_child_receipt(value: object) -> Optional[dict[str, object]]:
    if type(value) is not dict:
        return None
    try:
        encoded = (json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")
    except (TypeError, ValueError, UnicodeError):
        return None
    parsed = parse_i13_child_receipt(encoded)
    return parsed if type(parsed) is dict and parsed == value else None


def _parent_confirms_i13_diagnostic(result: object, expected_config_index: object) -> bool:
    """Accept only paired SDK+adapter evidence and verified Job cleanup."""

    if type(result) is not SupervisedResult:
        return False
    receipt = _exact_i13_child_receipt(result.sdk_receipt)
    evidence = result.process_evidence
    if receipt is None or type(evidence) is not ProcessEvidence:
        return False
    if (
        type(expected_config_index) is not int
        or not 0 <= expected_config_index < 8
        or receipt["diagnostic_id"] != "i13_oneshot_md_diagnostic"
        or receipt["status"] != "diagnostic_complete"
        or receipt["reason"] != "matching_tick_observed"
        or receipt["stage"] != "market_data"
        or receipt["selected_pair_index"] != f"pair_{expected_config_index}"
        or receipt["parent_precheck_binding_match"] is not True
        or receipt["credential_resolver_invoked"] is not True
        or receipt["sdk_imported"] is not True
        or receipt["source_identity_verified"] is not True
        or receipt["sdk_receipt_observed"] is not True
        or receipt["sdk_evidence_integrity"] != "valid"
        or receipt["sdk_login_callback_count"] != "one"
        or receipt["sdk_login_disposition"] != "accepted"
        or receipt["sdk_request_id_relation"] != "zero"
        or receipt["sdk_response_error_status"] != "zero"
        or receipt["sdk_broker_id_shape"] != "exact_match"
        or receipt["sdk_user_id_shape"] != "exact_match"
        or receipt["sdk_trading_day_shape"] != "valid"
        or receipt["sdk_native_broker_id_shape"] != "nonempty_terminated"
        or receipt["sdk_native_user_id_shape"] != "nonempty_terminated"
        or receipt["sdk_receipt_terminal_state"] != "complete"
        or receipt["sdk_subscription_submitted"] is not True
        or receipt["sdk_subscription_error_status"] != "zero"
        or receipt["sdk_subscription_acknowledged"] is not True
        or receipt["sdk_first_tick_pending"] is not False
        or receipt["sdk_first_tick_received"] is not True
        or receipt["adapter_evidence_integrity"] != "valid"
        or receipt["adapter_login_identity_state"] != "verified"
        or receipt["adapter_acknowledgement_state"] != "acknowledged"
        or receipt["adapter_ack_tick_order"] != "ack_before_all_ticks"
        or receipt["adapter_tick_classification"] != "tick_accepted"
        or receipt["adapter_tick_arrival_count"] != "one"
        or receipt["adapter_accepted_tick_count"] != "one"
        or receipt["adapter_same_trading_day_observed"] is not True
        or receipt["adapter_native_join_state"] != "completed"
        or receipt["close_state"] != "verified_closed"
        or receipt["client_stop_returned"] is not True
        or receipt["native_join_pending"] is not False
        or receipt["probe_session_closed"] is not True
        or any(
            receipt[name] is not False for name in ("order_submission_authorized", "trading_ready")
        )
        or receipt["trading_writes_zero"] is not True
        or receipt["settlement_writes_zero"] is not True
    ):
        return False
    return (
        result.status == "child_exited"
        and result.reason == "child_process_exited"
        and evidence.process_created is True
        and evidence.job_assignment_observed is True
        and evidence.process_resumed is True
        and evidence.process_exit_observed is True
        and evidence.process_exit_code == 0
        and evidence.job_termination_requested is False
        and evidence.job_termination_call_succeeded is None
        and evidence.job_empty_observed is True
        and evidence.containment == "verified"
        and result.retained_control is None
    )


def _is_concrete_path(path: Path, *, directory: bool) -> bool:
    if not path.is_absolute():
        return False
    current = Path(path.anchor)
    parts = path.parts[1:]
    for index, part in enumerate(parts):
        current = current / part
        try:
            result = os.lstat(current)
        except OSError:
            return False
        if stat.S_ISLNK(result.st_mode) or bool(getattr(result, "st_file_attributes", 0) & 0x400):
            return False
        expected_directory = index < len(parts) - 1 or directory
        if expected_directory and not stat.S_ISDIR(result.st_mode):
            return False
        if not expected_directory and not stat.S_ISREG(result.st_mode):
            return False
    return True


def _verify_i13_at_fixed_install_root(verifier: Callable[[], Any]) -> Any:
    """Run an artifact verifier with only I13's fixed venv install root."""

    if not callable(verifier):
        raise TypeError("i13_artifact_verifier_required")
    provenance = importlib.import_module("backtrader_runtime.ctp_artifact_provenance")
    original = getattr(provenance, "_interpreter_install_roots", None)
    fixed_root = _I13_RUNTIME_ROOT / "Lib" / "site-packages"
    if not callable(original) or not _is_concrete_path(fixed_root, directory=True):
        raise I13SourceIdentityError("i13_fixed_artifact_root_unavailable")
    resolved_fixed_root = fixed_root.resolve(strict=True)

    def _only_fixed_i13_venv() -> tuple[Path, ...]:
        if not _is_concrete_path(fixed_root, directory=True):
            raise I13SourceIdentityError("i13_fixed_artifact_root_unavailable")
        current = fixed_root.resolve(strict=True)
        if os.path.normcase(str(current)) != os.path.normcase(str(resolved_fixed_root)):
            raise I13SourceIdentityError("i13_fixed_artifact_root_changed")
        return (resolved_fixed_root,)

    provenance._interpreter_install_roots = _only_fixed_i13_venv
    try:
        return verifier()
    finally:
        provenance._interpreter_install_roots = original


@contextmanager
def _trusted_i13_installed_capability_import_context(
    capability_modules: Sequence[str],
) -> Any:
    """Enter the strict SDK origin fence with I13's one exact venv root.

    CPython ``-S`` intentionally omits venv site processing, so sysconfig
    points at the base interpreter. The child inserts the fixed I13
    site-packages directory explicitly. Temporarily override only the strict
    resolver's root provider while its context manager eagerly captures
    origins; restore it before yielding to any credential or SDK code.
    """

    capability_imports = importlib.import_module("backtrader_runtime.capability_imports")
    original_roots = getattr(capability_imports, "_concrete_interpreter_install_roots", None)
    context_factory = getattr(
        capability_imports, "trusted_installed_capability_import_context", None
    )
    fixed_root = _I13_RUNTIME_ROOT / "Lib" / "site-packages"
    if (
        not callable(original_roots)
        or not callable(context_factory)
        or not _is_concrete_path(fixed_root, directory=True)
    ):
        raise I13SourceIdentityError("i13_fixed_capability_root_unavailable")
    resolved_root = fixed_root.resolve(strict=True)

    def _only_fixed_i13_venv() -> tuple[Path, ...]:
        if not _is_concrete_path(fixed_root, directory=True):
            raise I13SourceIdentityError("i13_fixed_capability_root_unavailable")
        current = fixed_root.resolve(strict=True)
        if os.path.normcase(str(current)) != os.path.normcase(str(resolved_root)):
            raise I13SourceIdentityError("i13_fixed_capability_root_changed")
        return (resolved_root,)

    manager = context_factory(capability_modules)
    capability_imports._concrete_interpreter_install_roots = _only_fixed_i13_venv
    try:
        manager.__enter__()
    finally:
        capability_imports._concrete_interpreter_install_roots = original_roots

    try:
        yield
    except BaseException:
        if not manager.__exit__(*sys.exc_info()):
            raise
    else:
        manager.__exit__(None, None, None)


def _i13_source_guard_code(source_root: Path) -> str:
    """Return a standard-library-only pre-import source/cache guard."""

    root_literal = str(source_root)
    site_packages_literal = str(_I13_RUNTIME_ROOT / "Lib" / "site-packages")
    evidence_root_literal = str(_I13_EVIDENCE_ROOT)
    return "\n".join(
        (
            "import hashlib, json, os, stat, sys",
            f"_i13_root = {root_literal!r}",
            f"_i13_site_packages = {site_packages_literal!r}",
            f"_i13_evidence_root = {evidence_root_literal!r}",
            f"_i13_pinned_manifest = {I13_SOURCE_MANIFEST_SHA256!r}",
            f"_i13_manifest_env = {_I13_SOURCE_MANIFEST_ENV!r}",
            f"_i13_cache_env = {_I13_PYCACHE_PREFIX_ENV!r}",
            "_i13_cache_prefix = os.environ.get(_i13_cache_env)",
            "if (sys.flags.isolated != 1 or sys.flags.no_site != 1 or not sys.dont_write_bytecode or type(_i13_cache_prefix) is not str or not os.path.isabs(_i13_cache_prefix)): raise SystemExit(2)",
            "if os.path.normcase(os.path.abspath(sys.pycache_prefix or '')) != os.path.normcase(os.path.abspath(_i13_cache_prefix)): raise SystemExit(2)",
            "if os.path.normcase(os.path.dirname(os.path.abspath(_i13_cache_prefix))) != os.path.normcase(os.path.abspath(_i13_evidence_root)): raise SystemExit(2)",
            "_i13_evidence_stat = os.lstat(_i13_evidence_root)",
            "if not stat.S_ISDIR(_i13_evidence_stat.st_mode) or stat.S_ISLNK(_i13_evidence_stat.st_mode) or getattr(_i13_evidence_stat, 'st_file_attributes', 0) & 0x400: raise SystemExit(2)",
            "_i13_prefix_stat = os.lstat(_i13_cache_prefix)",
            "if not stat.S_ISDIR(_i13_prefix_stat.st_mode) or stat.S_ISLNK(_i13_prefix_stat.st_mode) or getattr(_i13_prefix_stat, 'st_file_attributes', 0) & 0x400: raise SystemExit(2)",
            "with os.scandir(_i13_cache_prefix) as _i13_prefix_entries:\n    if next(_i13_prefix_entries, None) is not None: raise SystemExit(2)",
            "if os.environ.get(_i13_manifest_env) != _i13_pinned_manifest: raise SystemExit(2)",
            "_i13_manifest_path = os.path.join(_i13_root, 'backtrader_runtime', 'ctp_i13_source_manifest.json')",
            "_i13_root_stat = os.lstat(_i13_root)",
            "if not stat.S_ISDIR(_i13_root_stat.st_mode) or stat.S_ISLNK(_i13_root_stat.st_mode) or getattr(_i13_root_stat, 'st_file_attributes', 0) & 0x400: raise SystemExit(2)",
            "_i13_stat = os.lstat(_i13_manifest_path)",
            "if not stat.S_ISREG(_i13_stat.st_mode) or stat.S_ISLNK(_i13_stat.st_mode) or getattr(_i13_stat, 'st_file_attributes', 0) & 0x400: raise SystemExit(2)",
            "with open(_i13_manifest_path, 'rb') as _i13_stream: _i13_manifest_raw = _i13_stream.read(131073)",
            "if not _i13_manifest_raw or len(_i13_manifest_raw) > 131072 or hashlib.sha256(_i13_manifest_raw).hexdigest() != _i13_pinned_manifest: raise SystemExit(2)",
            "try: _i13_manifest = json.loads(_i13_manifest_raw.decode('utf-8'))",
            "except Exception: raise SystemExit(2)",
            "if type(_i13_manifest) is not dict or set(_i13_manifest) != {'schema', 'source_files'} or _i13_manifest.get('schema') != 1: raise SystemExit(2)",
            "_i13_files = _i13_manifest.get('source_files')",
            "if type(_i13_files) is not dict or not 1 <= len(_i13_files) <= 256 or list(_i13_files) != sorted(_i13_files): raise SystemExit(2)",
            "_i13_expected_names = {'backtrader_runtime/ctp_i13_source_identity_pin.py', 'backtrader_runtime/ctp_i15_source_identity_pin.py'}",
            "_i13_actual_names = set()",
            "_i13_package_root = os.path.join(_i13_root, 'backtrader_runtime')",
            "def _i13_walk_error(_error): raise SystemExit(2)",
            "for _i13_current, _i13_dirs, _i13_names in os.walk(_i13_package_root, topdown=True, followlinks=False, onerror=_i13_walk_error):",
            "    _i13_kept = []",
            "    for _i13_dir in _i13_dirs:",
            "        _i13_dir_path = os.path.join(_i13_current, _i13_dir)",
            "        _i13_dir_stat = os.lstat(_i13_dir_path)",
            "        if not stat.S_ISDIR(_i13_dir_stat.st_mode) or stat.S_ISLNK(_i13_dir_stat.st_mode) or getattr(_i13_dir_stat, 'st_file_attributes', 0) & 0x400: raise SystemExit(2)",
            "        if _i13_dir == '__pycache__': continue",
            "        _i13_kept.append(_i13_dir)",
            "    _i13_dirs[:] = _i13_kept",
            "    for _i13_name in _i13_names:",
            "        _i13_file_path = os.path.join(_i13_current, _i13_name)",
            "        _i13_file_stat = os.lstat(_i13_file_path)",
            "        if stat.S_ISLNK(_i13_file_stat.st_mode) or getattr(_i13_file_stat, 'st_file_attributes', 0) & 0x400 or _i13_name.endswith(('.pyc', '.pyo', '.pyd', '.so', '.dll')): raise SystemExit(2)",
            "        if _i13_name.endswith('.py'): _i13_actual_names.add(os.path.relpath(_i13_file_path, _i13_root).replace(os.sep, '/'))",
            "if _i13_actual_names != set(_i13_files) | _i13_expected_names: raise SystemExit(2)",
            "for _i13_name, _i13_hash in _i13_files.items():",
            "    if type(_i13_name) is not str or type(_i13_hash) is not str or len(_i13_hash) != 64 or any(_i13_char not in '0123456789abcdef' for _i13_char in _i13_hash): raise SystemExit(2)",
            "    if not _i13_name.startswith('backtrader_runtime/') or not _i13_name.endswith('.py') or '\\\\' in _i13_name or any(_i13_part in {'', '.', '..'} for _i13_part in _i13_name.split('/')): raise SystemExit(2)",
            "    _i13_target = _i13_root",
            "    for _i13_part in _i13_name.split('/'):",
            "        _i13_target = os.path.join(_i13_target, _i13_part)",
            "        _i13_target_stat = os.lstat(_i13_target)",
            "        if stat.S_ISLNK(_i13_target_stat.st_mode) or getattr(_i13_target_stat, 'st_file_attributes', 0) & 0x400: raise SystemExit(2)",
            "    if not stat.S_ISREG(_i13_target_stat.st_mode): raise SystemExit(2)",
            "    with open(_i13_target, 'rb') as _i13_stream:",
            "        _i13_hash = hashlib.sha256(_i13_stream.read()).hexdigest()",
            "    if _i13_hash != _i13_files[_i13_name]: raise SystemExit(2)",
            "for _i13_name in _i13_expected_names:",
            "    _i13_target = os.path.join(_i13_root, *_i13_name.split('/'))",
            "    _i13_target_stat = os.lstat(_i13_target)",
            "    if not stat.S_ISREG(_i13_target_stat.st_mode) or stat.S_ISLNK(_i13_target_stat.st_mode) or getattr(_i13_target_stat, 'st_file_attributes', 0) & 0x400: raise SystemExit(2)",
            "_i13_site_stat = os.lstat(_i13_site_packages)",
            "if not stat.S_ISDIR(_i13_site_stat.st_mode) or stat.S_ISLNK(_i13_site_stat.st_mode) or getattr(_i13_site_stat, 'st_file_attributes', 0) & 0x400: raise SystemExit(2)",
            "import importlib.abc, importlib.machinery, importlib.util",
            "class _I13SourceOnlyLoader(importlib.machinery.SourceFileLoader):",
            "    def get_code(self, _fullname):",
            "        with open(self.path, 'rb') as _i13_source_stream: return self.source_to_code(_i13_source_stream.read(), self.path)",
            "class _I13SourceOnlyFinder(importlib.abc.MetaPathFinder):",
            "    def find_spec(self, _i13_fullname, _i13_path=None, _i13_target=None):",
            "        if _i13_fullname != 'backtrader_runtime' and not _i13_fullname.startswith('backtrader_runtime.'): return None",
            "        _i13_suffix = _i13_fullname.removeprefix('backtrader_runtime').lstrip('.')",
            "        _i13_parts = _i13_suffix.split('.') if _i13_suffix else []",
            "        if any(not _i13_part.isidentifier() for _i13_part in _i13_parts): raise ModuleNotFoundError(_i13_fullname)",
            "        _i13_base = os.path.join(_i13_package_root, *_i13_parts)",
            "        _i13_package_file = os.path.join(_i13_base, '__init__.py')",
            "        _i13_module_file = _i13_base + '.py'",
            "        if os.path.isfile(_i13_package_file): _i13_module_file = _i13_package_file",
            "        elif not os.path.isfile(_i13_module_file): raise ModuleNotFoundError(_i13_fullname)",
            "        _i13_candidate = _i13_module_file",
            "        _i13_relative = os.path.relpath(_i13_candidate, _i13_root).replace(os.sep, '/')",
            "        if _i13_relative not in set(_i13_files) | _i13_expected_names: raise ModuleNotFoundError(_i13_fullname)",
            "        _i13_loader = _I13SourceOnlyLoader(_i13_fullname, _i13_candidate)",
            "        _i13_is_package = _i13_candidate == _i13_package_file",
            "        return importlib.util.spec_from_file_location(_i13_fullname, _i13_candidate, loader=_i13_loader, submodule_search_locations=[os.path.dirname(_i13_candidate)] if _i13_is_package else None)",
            "sys.meta_path.insert(0, _I13SourceOnlyFinder())",
            "sys.path.insert(0, _i13_root)",
            "sys.path.insert(1, _i13_site_packages)",
            "",
        )
    )


def _fixed_i13_child_command(
    binding: I12FrontPrecheckBinding, cache_prefix: Optional[Path] = None
) -> Optional[FixedChildCommand]:
    """Bind the worker to the exact audited I13 venv and selected sealed pair."""

    if (
        os.name != "nt"
        or I13_SDK_SOURCE_COMMIT != "c68bebe8631419801e7a24e13b98c42867df0beb"
        or I13_CTP_WHEEL_SHA256
        != "c6eb83c1389b8f0e96edf9f727c20901b2411961489e19abb4ee1aef6ec2ce5d"
        or type(binding) is not I12FrontPrecheckBinding
        or not isinstance(cache_prefix, Path)
        or not _is_concrete_path(cache_prefix, directory=True)
    ):
        return None
    if (
        not _is_concrete_path(_I13_RUNTIME_ROOT, directory=True)
        or not _is_concrete_path(_I13_INTERPRETER, directory=False)
        or not _is_concrete_path(_I13_RUNTIME_ROOT / "pyvenv.cfg", directory=False)
        or not _is_concrete_path(_I13_RUNTIME_ROOT / "Lib" / "site-packages", directory=True)
        or not _is_concrete_path(_I13_EVIDENCE_ROOT, directory=True)
    ):
        return None
    try:
        lines = (_I13_RUNTIME_ROOT / "pyvenv.cfg").read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeError):
        return None
    normalized = {line.strip().casefold() for line in lines}
    if (
        "include-system-site-packages = false" not in normalized
        or "version = 3.11.5" not in normalized
        or "home = c:\\anaconda3" not in normalized
    ):
        return None
    system_root = os.environ.get("SYSTEMROOT") or os.environ.get("WINDIR")
    temp_dir = os.environ.get("TEMP") or os.environ.get("TMP")
    if (
        type(system_root) is not str
        or not Path(system_root).is_absolute()
        or type(temp_dir) is not str
        or not Path(temp_dir).is_absolute()
    ):
        return None
    environment = {
        "SYSTEMROOT": system_root,
        "WINDIR": system_root,
        "PATH": ";".join(
            (
                str(_I13_INTERPRETER.parent),
                str(_I13_BASE_PYTHON_ROOT),
                str(Path(system_root) / "System32"),
            )
        ),
        "TEMP": temp_dir,
        "TMP": temp_dir,
        "PYTHONNOUSERSITE": "1",
        "PYTHONDONTWRITEBYTECODE": "1",
        "PYTHONUNBUFFERED": "1",
        "PYTHONUTF8": "1",
        _I12_PRECHECK_INDEX_ENV: str(binding.config_index),
        _I12_PRECHECK_BINDING_ENV: binding.binding_sha256,
    }
    source_root = Path(__file__).resolve().parents[1]
    try:
        verify_i13_source_identity(source_root, expected_manifest_sha256=I13_SOURCE_MANIFEST_SHA256)
    except I13SourceIdentityError:
        return None
    environment[_I13_SOURCE_MANIFEST_ENV] = I13_SOURCE_MANIFEST_SHA256
    environment[_I13_PYCACHE_PREFIX_ENV] = str(cache_prefix)
    child_source = _i13_source_guard_code(source_root) + (
        "from backtrader_runtime.ctp_i13_md_oneshot_supervisor import "
        "_run_i13_child_entry; raise SystemExit(_run_i13_child_entry())\n"
    )
    try:
        return FixedChildCommand(
            (
                str(_I13_INTERPRETER),
                "-I",
                "-S",
                "-B",
                "-X",
                f"pycache_prefix={cache_prefix}",
                "-c",
                child_source,
            ),
            source_root,
            environment,
            job_handle_env_name=_I13_JOB_HANDLE_ENV,
        )
    except (OSError, TypeError, ValueError):
        return None


def _fixed_i13_artifact_preflight_command(
    worker_command: FixedChildCommand,
) -> Optional[FixedChildCommand]:
    """Build the metadata-only verifier Job before reserving the I13 marker."""

    if type(worker_command) is not FixedChildCommand:
        return None
    cache_prefix = worker_command.env.get(_I13_PYCACHE_PREFIX_ENV)
    if (
        type(cache_prefix) is not str
        or not Path(cache_prefix).is_absolute()
        or not _is_concrete_path(Path(cache_prefix), directory=True)
    ):
        return None
    source_root = str(worker_command.cwd)
    try:
        verify_i13_source_identity(source_root, expected_manifest_sha256=I13_SOURCE_MANIFEST_SHA256)
    except I13SourceIdentityError:
        return None
    code = _i13_source_guard_code(Path(source_root)) + (
        "payload = {'credential_resolver_invoked': False, 'native_join_pending': False, "
        "'reason': 'artifact_rejected', 'sdk_imported': False, "
        "'source_identity_verified': True, 'status': 'rejected'}\n"
        "try:\n"
        "    from backtrader_runtime.ctp_i13_source_identity import "
        "verify_i13_runtime_import_origins\n"
        f"    verify_i13_runtime_import_origins({source_root!r})\n"
        "    from backtrader_runtime.ctp_artifact_provenance import "
        "CTP_I13_ONESHOT_MD_DIAGNOSTIC_ARTIFACT_PINS, "
        "verify_ctp_i13_oneshot_md_diagnostic_artifact_provenance_for_fronts\n"
        "    from backtrader_runtime.ctp_i13_md_oneshot_supervisor import "
        "I13_CTP_WHEEL_SHA256, I13_SDK_SOURCE_COMMIT, "
        "_trusted_i13_installed_capability_import_context, "
        "_verify_i13_at_fixed_install_root\n"
        f"    verify_i13_runtime_import_origins({source_root!r})\n"
        "    facts = lambda pin: (pin.distribution, pin.module, pin.version, "
        "pin.wheel_filename, pin.wheel_sha256, pin.record_sha256)\n"
        "    expected_base = ('bt_api_base', 'bt_api_base', '0.15.5', "
        "'bt_api_base-0.15.5-py3-none-any.whl', "
        "'2f413f7e914c4bbd1dcd47b3b95a3fb36e224dda2c4db97bdda35bf61797ad68', "
        "'6f73003cdba8f15468faa0264eb99c81578e6648c00ebf5de4c7161c676f7113')\n"
        "    expected_ctp = ('bt_api_ctp', 'bt_api_ctp', '2.0.3+iteration41.i13', "
        "'bt_api_ctp-2.0.3+iteration41.i13-cp311-cp311-win_amd64.whl', "
        "'c6eb83c1389b8f0e96edf9f727c20901b2411961489e19abb4ee1aef6ec2ce5d', "
        "'d21876f577927651a585ad7273c5bdcf508d65766f2a05e2f5a06c8a29798217')\n"
        "    pins = CTP_I13_ONESHOT_MD_DIAGNOSTIC_ARTIFACT_PINS\n"
        "    if I13_SDK_SOURCE_COMMIT != 'c68bebe8631419801e7a24e13b98c42867df0beb': raise RuntimeError()\n"
        "    if I13_CTP_WHEEL_SHA256 != expected_ctp[4]: raise RuntimeError()\n"
        "    if set(pins) != {'bt_api_base', 'bt_api_ctp'}: raise RuntimeError()\n"
        "    if facts(pins['bt_api_base']) != expected_base or facts(pins['bt_api_ctp']) != expected_ctp: raise RuntimeError()\n"
        "    blocked = ('backtrader_runtime.credential_resolver', 'bt_api_base', 'bt_api_ctp')\n"
        "    if any(name in sys.modules for name in blocked): raise RuntimeError()\n"
        "    with _trusted_i13_installed_capability_import_context(('bt_api_base', 'bt_api_ctp')):\n"
        "        _verify_i13_at_fixed_install_root(lambda: "
        "verify_ctp_i13_oneshot_md_diagnostic_artifact_provenance_for_fronts("
        "td_front='tcp://127.0.0.1:10130', md_front='tcp://127.0.0.1:10131'))\n"
        "    if any(name in sys.modules for name in ('bt_api_base', 'bt_api_ctp')): raise RuntimeError()\n"
        "    payload.update(reason='artifact_verified', status='verified')\n"
        "except Exception:\n"
        "    pass\n"
        "sys.stdout.write(json.dumps(payload, sort_keys=True, separators=(',', ':')) + '\\n')\n"
        "raise SystemExit(0 if payload['status'] == 'verified' else 2)\n"
    )
    environment = {
        key: value
        for key, value in worker_command.env.items()
        if key not in {_I12_PRECHECK_INDEX_ENV, _I12_PRECHECK_BINDING_ENV}
    }
    environment[_I13_SOURCE_MANIFEST_ENV] = I13_SOURCE_MANIFEST_SHA256
    environment[_I13_PYCACHE_PREFIX_ENV] = cache_prefix
    try:
        return FixedChildCommand(
            (
                str(_I13_INTERPRETER),
                "-I",
                "-S",
                "-B",
                "-X",
                f"pycache_prefix={cache_prefix}",
                "-c",
                code,
            ),
            worker_command.cwd,
            environment,
        )
    except (OSError, TypeError, ValueError):
        return None


class _I13ArtifactPreflightLatch:
    """Process-local latch for the metadata-only artifact verifier Job."""

    def __init__(self) -> None:
        self._tripped = False

    def is_tripped(self) -> bool:
        return self._tripped

    def trip(self, _reason: str) -> bool:
        self._tripped = True
        return True


def _parse_i13_artifact_preflight_receipt(raw: bytes) -> Optional[Mapping[str, object]]:
    return parse_single_json_receipt(raw, _I13_ARTIFACT_PREFLIGHT_SCHEMA)


def _i13_artifact_preflight_succeeded(result: object) -> bool:
    if type(result) is not SupervisedResult:
        return False
    receipt = result.sdk_receipt
    evidence = result.process_evidence
    try:
        valid_receipt = (
            type(receipt) is dict
            and _parse_i13_artifact_preflight_receipt(
                (json.dumps(receipt, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")
            )
            == receipt
        )
    except (TypeError, ValueError, UnicodeError):
        valid_receipt = False
    return (
        valid_receipt
        and receipt["status"] == "verified"
        and receipt["reason"] == "artifact_verified"
        and receipt["credential_resolver_invoked"] is False
        and receipt["sdk_imported"] is False
        and receipt["source_identity_verified"] is True
        and receipt["native_join_pending"] is False
        and type(evidence) is ProcessEvidence
        and result.status == "child_exited"
        and result.reason == "child_process_exited"
        and evidence.process_created is True
        and evidence.job_assignment_observed is True
        and evidence.process_resumed is True
        and evidence.process_exit_observed is True
        and evidence.process_exit_code == 0
        and evidence.job_termination_requested is False
        and evidence.job_termination_call_succeeded is None
        and evidence.job_empty_observed is True
        and evidence.containment == "verified"
        and result.retained_control is None
    )


def _i13_deadline_expired(deadline_monotonic: float) -> bool:
    try:
        return time.monotonic() >= deadline_monotonic
    except Exception:
        return True


def _read_child_deadline() -> Optional[float]:
    raw = os.environ.pop(_I13_DEADLINE_ENV, None)
    if type(raw) is not str or len(raw) > 64:
        return None
    try:
        deadline = float(raw)
    except (OverflowError, ValueError):
        return None
    return deadline if math.isfinite(deadline) and deadline > 0 else None


def _supervise_i13_child_under_source_lease(
    *,
    deadline_monotonic: float,
    source_identity_manifest_sha256: str,
    cache_prefix: Path,
    precheck: Optional[Callable[[float], I12FrontPrecheckBinding]] = None,
    command_builder: Optional[
        Callable[[I12FrontPrecheckBinding], Optional[FixedChildCommand]]
    ] = None,
    artifact_command_builder: Optional[
        Callable[[FixedChildCommand], Optional[FixedChildCommand]]
    ] = None,
    latch_factory: Optional[Callable[[Path], FailClosedLatch]] = None,
    runner: Optional[Callable[..., SupervisedResult]] = None,
) -> I13DiagnosticReport:
    """Use one absolute budget for config/front selection, both Jobs, and close."""

    global _I13_RETAINED_JOB_CONTROL
    if os.name != "nt":
        return I13DiagnosticReport(
            "supervisor_error", "windows_required", False, None, None, "unavailable", None
        )
    if _i13_deadline_expired(deadline_monotonic):
        return I13DiagnosticReport(
            "incomplete", "child_deadline_exceeded", False, None, None, "not_started", None
        )
    try:
        binding = (
            _parent_credential_free_precheck(deadline_monotonic=deadline_monotonic)
            if precheck is None
            else precheck(deadline_monotonic)
        )
    except Exception:
        return I13DiagnosticReport(
            "rejected", "front_precheck_failed", False, None, None, "not_started", None
        )
    if _i13_deadline_expired(deadline_monotonic):
        return I13DiagnosticReport(
            "incomplete", "child_deadline_exceeded", False, None, None, "not_started", None
        )
    if type(binding) is not I12FrontPrecheckBinding:
        return I13DiagnosticReport(
            "rejected", "front_precheck_failed", False, None, None, "not_started", None
        )
    try:
        command = (
            _fixed_i13_child_command(binding, cache_prefix)
            if command_builder is None
            else command_builder(binding)
        )
        if command is not None:
            child_environment = dict(command.env)
            child_environment[_I13_DEADLINE_ENV] = repr(deadline_monotonic)
            child_environment[_I13_SOURCE_MANIFEST_ENV] = source_identity_manifest_sha256
            child_environment[_I13_PYCACHE_PREFIX_ENV] = str(cache_prefix)
            command = FixedChildCommand(
                command.argv,
                command.cwd,
                child_environment,
                job_handle_env_name=command.job_handle_env_name,
            )
        artifact_command = (
            (
                _fixed_i13_artifact_preflight_command(command)
                if artifact_command_builder is None
                else artifact_command_builder(command)
            )
            if command is not None
            else None
        )
    except Exception:
        command = artifact_command = None
    if command is None or artifact_command is None:
        return I13DiagnosticReport(
            "supervisor_error",
            "i13_runtime_unavailable",
            False,
            binding.config_index,
            False,
            "not_started",
            None,
        )
    if _i13_deadline_expired(deadline_monotonic):
        return I13DiagnosticReport(
            "incomplete",
            "child_deadline_exceeded",
            False,
            binding.config_index,
            None,
            "not_started",
            None,
        )
    active_runner = runner or run_readonly_child
    try:
        artifact_result = active_runner(
            artifact_command,
            _parse_i13_artifact_preflight_receipt,
            receipt_schema=_I13_ARTIFACT_PREFLIGHT_SCHEMA,
            fail_closed_latch=_I13ArtifactPreflightLatch(),
            deadline_seconds=_I13_ARTIFACT_PREFLIGHT_SECONDS,
            deadline_monotonic=deadline_monotonic,
            max_stdout_bytes=4096,
            termination_grace_seconds=2.0,
        )
    except Exception:
        return I13DiagnosticReport(
            "supervisor_error",
            "i13_supervisor_failed",
            False,
            binding.config_index,
            False,
            "unavailable",
            None,
        )
    if type(artifact_result) is SupervisedResult and artifact_result.retained_control is not None:
        _I13_RETAINED_JOB_CONTROL = artifact_result.retained_control
    artifact_evidence = (
        artifact_result.process_evidence
        if type(artifact_result) is SupervisedResult
        and type(artifact_result.process_evidence) is ProcessEvidence
        else _empty_evidence("unavailable")
    )
    artifact_containment = artifact_evidence.containment
    if _i13_deadline_expired(deadline_monotonic):
        return I13DiagnosticReport(
            "incomplete",
            "child_deadline_exceeded",
            False,
            binding.config_index,
            False,
            artifact_containment,
            artifact_result if type(artifact_result) is SupervisedResult else None,
        )
    if not _i13_artifact_preflight_succeeded(artifact_result):
        return I13DiagnosticReport(
            "rejected" if artifact_containment == "verified" else "supervisor_error",
            "sdk_artifact_rejected"
            if artifact_containment == "verified"
            else "i13_supervisor_failed",
            False,
            binding.config_index,
            False,
            artifact_containment,
            artifact_result if type(artifact_result) is SupervisedResult else None,
        )
    make_latch = latch_factory or PersistentI13OneShotAttemptLatch
    try:
        latch = make_latch(I13_LATCH_PATH)
        begin_attempt = getattr(latch, "begin_attempt", None)
        if not callable(begin_attempt):
            raise TypeError("i13_latch_unavailable")
        if _i13_deadline_expired(deadline_monotonic):
            return I13DiagnosticReport(
                "incomplete",
                "child_deadline_exceeded",
                False,
                binding.config_index,
                True,
                artifact_containment,
                None,
            )
        if begin_attempt() is not True:
            return I13DiagnosticReport(
                "latched",
                "prior_attempt_or_poisoned_latch",
                False,
                binding.config_index,
                True,
                artifact_containment,
                None,
            )
    except Exception:
        return I13DiagnosticReport(
            "supervisor_error",
            "i13_latch_unavailable",
            False,
            binding.config_index,
            True,
            artifact_containment,
            None,
        )
    if _i13_deadline_expired(deadline_monotonic):
        return I13DiagnosticReport(
            "incomplete",
            "child_deadline_exceeded",
            True,
            binding.config_index,
            True,
            artifact_containment,
            None,
        )
    try:
        result = active_runner(
            command,
            parse_i13_child_receipt,
            receipt_schema=I13_CHILD_RECEIPT_SCHEMA,
            fail_closed_latch=latch,
            deadline_seconds=_I13_TOTAL_DEADLINE_SECONDS,
            deadline_monotonic=deadline_monotonic,
            max_stdout_bytes=_I13_MAX_STDOUT_BYTES,
            termination_grace_seconds=_I13_TERMINATION_GRACE_SECONDS,
        )
    except Exception:
        return I13DiagnosticReport(
            "supervisor_error",
            "i13_supervisor_failed",
            True,
            binding.config_index,
            True,
            artifact_containment,
            None,
        )
    if type(result) is not SupervisedResult:
        return I13DiagnosticReport(
            "supervisor_error",
            "i13_supervisor_result_invalid",
            True,
            binding.config_index,
            True,
            artifact_containment,
            None,
        )
    if result.retained_control is not None:
        _I13_RETAINED_JOB_CONTROL = result.retained_control
    if _i13_deadline_expired(deadline_monotonic):
        result = SupervisedResult(
            "timed_out",
            "child_deadline_exceeded",
            result.sdk_receipt,
            result.process_evidence,
            result.retained_control,
        )
    receipt = _exact_i13_child_receipt(result.sdk_receipt)
    if _parent_confirms_i13_diagnostic(result, binding.config_index):
        return I13DiagnosticReport(
            "diagnostic_complete",
            "matching_tick_observed",
            True,
            binding.config_index,
            True,
            artifact_containment,
            result,
        )
    if receipt is not None and receipt["native_join_pending"] is True:
        status, reason = "incomplete", "native_join_pending"
    elif receipt is not None and receipt["adapter_login_identity_state"] == "identity_unverified":
        status, reason = "incomplete", "identity_unverified"
    elif receipt is not None:
        status = "incomplete" if receipt["status"] == "incomplete" else "rejected"
        reason = (
            "adapter_observation_incomplete"
            if status == "incomplete"
            else "child_diagnostic_rejected"
        )
    elif result.status == "timed_out":
        status, reason = "incomplete", "child_deadline_exceeded"
    elif result.status in {"pending_native_join", "containment_error"}:
        status, reason = "incomplete", "native_join_pending"
    else:
        status, reason = "supervisor_error", "i13_supervisor_failed"
    return I13DiagnosticReport(
        status, reason, True, binding.config_index, True, artifact_containment, result
    )


def _supervise_i13_child(
    *,
    precheck: Optional[Callable[[float], I12FrontPrecheckBinding]] = None,
    command_builder: Optional[
        Callable[[I12FrontPrecheckBinding], Optional[FixedChildCommand]]
    ] = None,
    artifact_command_builder: Optional[
        Callable[[FixedChildCommand], Optional[FixedChildCommand]]
    ] = None,
    latch_factory: Optional[Callable[[Path], FailClosedLatch]] = None,
    runner: Optional[Callable[..., SupervisedResult]] = None,
    source_lease_factory: Optional[Callable[..., I13SourceLease]] = None,
) -> I13DiagnosticReport:
    """Pin and lock source code before parent config/front selection."""

    global _I13_RETAINED_SOURCE_LEASE
    deadline_monotonic = time.monotonic() + _I13_TOTAL_DEADLINE_SECONDS
    if os.name != "nt":
        return I13DiagnosticReport(
            "supervisor_error", "windows_required", False, None, None, "unavailable", None
        )
    if _I13_RETAINED_SOURCE_LEASE is not None or _I13_RETAINED_JOB_CONTROL is not None:
        return I13DiagnosticReport(
            "supervisor_error", "source_identity_unverified", False, None, None, "unavailable", None
        )
    if (
        type(I13_SOURCE_MANIFEST_SHA256) is not str
        or len(I13_SOURCE_MANIFEST_SHA256) != 64
        or any(char not in "0123456789abcdef" for char in I13_SOURCE_MANIFEST_SHA256)
    ):
        return I13DiagnosticReport(
            "supervisor_error", "source_identity_unverified", False, None, None, "not_started", None
        )
    if _i13_deadline_expired(deadline_monotonic):
        return I13DiagnosticReport(
            "incomplete", "child_deadline_exceeded", False, None, None, "not_started", None
        )
    source_root = Path(__file__).resolve().parents[1]
    lease: Optional[I13SourceLease] = None
    try:
        lease = (source_lease_factory or acquire_i13_source_lease)(
            source_root,
            expected_manifest_sha256=I13_SOURCE_MANIFEST_SHA256,
            cache_prefix_parent=_I13_EVIDENCE_ROOT,
        )
        if (
            type(lease) is not I13SourceLease
            or lease.manifest_sha256 != I13_SOURCE_MANIFEST_SHA256
            or not isinstance(lease.cache_prefix, Path)
        ):
            raise I13SourceIdentityError("source_identity_pin_mismatch")
        verify_i13_runtime_import_origins(source_root)
        lease.install_source_import_guard(source_root)
    except Exception:
        if lease is not None:
            try:
                lease.close()
            except Exception:
                _I13_RETAINED_SOURCE_LEASE = lease
        return I13DiagnosticReport(
            "supervisor_error",
            "source_identity_unverified",
            False,
            None,
            None,
            "not_started",
            None,
        )
    assert lease is not None
    if _i13_deadline_expired(deadline_monotonic):
        try:
            lease.close()
        except Exception:
            _I13_RETAINED_SOURCE_LEASE = lease
        return I13DiagnosticReport(
            "incomplete",
            "child_deadline_exceeded",
            False,
            None,
            None,
            "not_started",
            None,
            lease.manifest_sha256,
        )
    try:
        report = _supervise_i13_child_under_source_lease(
            deadline_monotonic=deadline_monotonic,
            source_identity_manifest_sha256=lease.manifest_sha256,
            cache_prefix=lease.cache_prefix,
            precheck=precheck,
            command_builder=command_builder,
            artifact_command_builder=artifact_command_builder,
            latch_factory=latch_factory,
            runner=runner,
        )
    except Exception:
        report = I13DiagnosticReport(
            "supervisor_error", "i13_supervisor_failed", False, None, None, "unavailable", None
        )
    if _I13_RETAINED_JOB_CONTROL is not None:
        _I13_RETAINED_SOURCE_LEASE = lease
    else:
        try:
            lease.close()
        except Exception:
            _I13_RETAINED_SOURCE_LEASE = lease
            return I13DiagnosticReport(
                "supervisor_error",
                "source_identity_unverified",
                report.attempt_reserved,
                report.selected_pair_index,
                report.artifact_pin_verified,
                report.artifact_job_containment,
                report.supervised,
            )
    return I13DiagnosticReport(
        report.status,
        report.reason,
        report.attempt_reserved,
        report.selected_pair_index,
        report.artifact_pin_verified,
        report.artifact_job_containment,
        report.supervised,
        lease.manifest_sha256,
    )


class PersistentI13OneShotAttemptLatch:
    """Lazy facade over the hardened latch primitive at I13's private path."""

    def __init__(self, path: Path = I13_LATCH_PATH) -> None:
        if os.path.normcase(os.path.normpath(os.fspath(path))) != os.path.normcase(
            os.path.normpath(os.fspath(I13_LATCH_PATH))
        ):
            raise ValueError("i13_latch_path_fixed")
        self._delegate: Optional[object] = None

    def _active_delegate(self) -> object:
        if self._delegate is None:
            from .ctp_i8_oneshot_md_diagnostic import _PersistentI8NoRetryLatch

            class _I13PersistentLatchPrimitive(_PersistentI8NoRetryLatch):
                _latch_content = _I13_MARKER_CONTENT

                def _verify_ancestor_chain(self) -> None:
                    registry = iteration41_runtime_registry()
                    registration = registry.require_runtime_dir(
                        ITERATION41_013_3_CTP_PRIVATE_RUNTIME_DIR
                    )
                    if registration.runtime_id != ITERATION41_013_3_CTP_PRIVATE_RUNTIME_ID:
                        raise OSError("latch_runtime_registration_invalid")
                    with registry.verified_runtime_directory(registration):
                        current = Path(self._path.anchor)
                        for component in self._path.parts[1:-1]:
                            current = current / component
                            result = os.lstat(current)
                            if (
                                stat.S_ISLNK(result.st_mode)
                                or bool(getattr(result, "st_file_attributes", 0) & 0x400)
                                or not stat.S_ISDIR(result.st_mode)
                            ):
                                raise OSError("latch_ancestor_invalid")

            self._delegate = _I13PersistentLatchPrimitive(I13_LATCH_PATH)
        return self._delegate

    def begin_attempt(self) -> bool:
        begin = getattr(self._active_delegate(), "begin_attempt", None)
        return begin() is True if callable(begin) else False

    def is_tripped(self) -> bool:
        check = getattr(self._active_delegate(), "is_tripped", None)
        return check() is True if callable(check) else False

    def trip(self, reason: str) -> bool:
        trip = getattr(self._active_delegate(), "trip", None)
        return trip(reason) is True if callable(trip) else False


class _I13EventRecorder:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._started = time.monotonic()
        self._events: list[I13MdEvent] = []
        self._tick_ordinal = 0
        self._elapsed_ms = 0

    def add(self, kind: I13EventKind, *, tick_ordinal: Optional[int] = None) -> None:
        with self._lock:
            elapsed = max(0, int((time.monotonic() - self._started) * 1000))
            self._elapsed_ms = max(self._elapsed_ms, elapsed)
            self._events.append(I13MdEvent(kind, tick_ordinal, None, self._elapsed_ms))

    def tick_arrived(self) -> int:
        with self._lock:
            self._tick_ordinal += 1
            ordinal = self._tick_ordinal
            elapsed = max(0, int((time.monotonic() - self._started) * 1000))
            self._elapsed_ms = max(self._elapsed_ms, elapsed)
            self._events.append(
                I13MdEvent(I13EventKind.TICK_ARRIVED, ordinal, None, self._elapsed_ms)
            )
            return ordinal

    def accept_observed_tick(self, *, same_trading_day: bool) -> None:
        with self._lock:
            if self._tick_ordinal != 1:
                return
            elapsed = max(0, int((time.monotonic() - self._started) * 1000))
            self._elapsed_ms = max(self._elapsed_ms, elapsed)
            self._events.append(I13MdEvent(I13EventKind.TICK_ACCEPTED, 1, None, self._elapsed_ms))
            if same_trading_day is True:
                self._events.append(
                    I13MdEvent(
                        I13EventKind.TICK_SAME_TRADING_DAY_CONFIRMED,
                        1,
                        None,
                        self._elapsed_ms,
                    )
                )

    def snapshot(self) -> tuple[I13MdEvent, ...]:
        with self._lock:
            return tuple(self._events)


def _tracked_i13_client_type(
    base_type: type, events: _I13EventRecorder, holder: dict[str, Any]
) -> type:
    """Capture callbacks/receipt while leaving the pinned SDK client behavior intact."""

    if (
        type(base_type) is not type
        or base_type.__name__ != "OneShotMdDiagnosticClient"
        or base_type.__module__ != "bt_api_ctp.ctp.client"
    ):
        raise TypeError("i13_md_client_type_invalid")

    def __init__(self: object, *args: object, **kwargs: object) -> None:
        base_type.__init__(self, *args, **kwargs)  # type: ignore[misc]
        holder["client"] = self

    def __setattr__(self: object, name: str, value: object) -> None:
        if (
            type(name) is str
            and callable(value)
            and name
            in {
                "on_disconnect",
                "on_identity_unverified",
                "on_subscribe",
                "on_tick",
            }
        ):
            callback = value

            def observed_callback(*args: object, **kwargs: object) -> object:
                if name == "on_tick":
                    events.tick_arrived()
                result = callback(*args, **kwargs)  # type: ignore[operator]
                if name == "on_identity_unverified":
                    events.add(I13EventKind.LOGIN_IDENTITY_UNVERIFIED)
                elif name == "on_disconnect":
                    events.add(I13EventKind.MARKET_FRONT_DISCONNECTED)
                elif name == "on_subscribe":
                    acknowledgement = getattr(self, "diagnostic_subscription_acknowledged", None)
                    events.add(
                        I13EventKind.SUBSCRIPTION_ACKNOWLEDGED
                        if acknowledgement is True
                        else I13EventKind.SUBSCRIPTION_REJECTED
                    )
                return result

            value = observed_callback
        base_type.__setattr__(self, name, value)  # type: ignore[misc]

    return type(
        "OneShotMdDiagnosticClient",
        (base_type,),
        {"__module__": base_type.__module__, "__init__": __init__, "__setattr__": __setattr__},
    )


def _safe_adapter_progress(error: object) -> object:
    try:
        from .ctp_i10_oneshot_md_readonly import CtpI10OneShotMdProgressEvidence

        value = getattr(error, "i10_progress_evidence", None)
        return value if type(value) is CtpI10OneShotMdProgressEvidence else None
    except Exception:
        return None


def _run_i13_market_adapter(
    *,
    admission: object,
    credential_source: object,
    client_type: type,
    stop_receipt_type: type,
    deadline_monotonic: float,
) -> tuple[
    object, object, tuple[I13MdEvent, ...], str, Optional[bool], Optional[bool], Optional[bool], str
]:
    """Reuse the strict main-repo I10 callback adapter with I13's pinned client."""

    from .ctp_i10_oneshot_md_readonly import probe_i10_oneshot_md_readonly

    events = _I13EventRecorder()
    holder: dict[str, Any] = {}
    tracked_type = _tracked_i13_client_type(client_type, events, holder)
    observation = None
    error: Optional[BaseException] = None
    try:
        remaining = max(0.0, deadline_monotonic - time.monotonic())
        if remaining <= 0:
            raise TimeoutError("probe_deadline_expired")
        observation = probe_i10_oneshot_md_readonly(
            admission=admission,
            credential_source=credential_source,
            client_type=tracked_type,
            stop_receipt_type=stop_receipt_type,
            timeout_seconds=min(_I13_MARKET_OBSERVATION_SECONDS, remaining),
        )
        events.accept_observed_tick(
            same_trading_day=getattr(observation, "same_trading_day_observed", None) is True
        )
    except Exception as caught:
        error = caught
    client = holder.get("client")
    sdk_receipt = None
    if client is not None:
        try:
            sdk_receipt = client.diagnostic_receipt
        except Exception:
            sdk_receipt = None
    close_state = "not_attempted"
    stop_returned: Optional[bool] = None
    join_pending: Optional[bool] = None
    session_closed: Optional[bool] = None
    login_state = "unavailable"
    progress = _safe_adapter_progress(error) if error is not None else None
    if observation is not None:
        login_state = getattr(observation, "login_identity_state", "unavailable")
        stop_returned = getattr(observation, "client_stop_returned", None)
        join_pending = getattr(observation, "native_join_pending", None)
        session_closed = getattr(observation, "probe_session_closed", None)
        close_state = (
            "verified_closed"
            if stop_returned is True and join_pending is False and session_closed is True
            else "native_join_pending"
            if join_pending is True
            else "stop_returned"
            if stop_returned is True
            else "unknown"
        )
        if close_state == "verified_closed":
            events.add(I13EventKind.NATIVE_JOIN_COMPLETED)
    elif error is not None:
        close_state_raw = getattr(error, "close_state", None)
        close_state = close_state_raw if close_state_raw in _I13_CLOSE_STATES else "unknown"
        stop_value = getattr(error, "client_stop_returned", None)
        stop_returned = stop_value if type(stop_value) is bool else None
        join_pending = (
            close_state == "native_join_pending" if close_state in _I13_CLOSE_STATES else None
        )
        session_closed = True if close_state == "verified_closed" else None
        if join_pending is True:
            events.add(I13EventKind.NATIVE_JOIN_PENDING)
        progress_state = getattr(progress, "login_identity_state", None)
        login_state = (
            progress_state
            if progress_state in {"verified", "identity_unverified"}
            else "unavailable"
        )
    events.add(I13EventKind.OBSERVATION_WINDOW_CLOSED)
    return (
        observation,
        sdk_receipt,
        events.snapshot(),
        close_state,
        stop_returned,
        join_pending,
        session_closed,
        login_state,
    )


def _child_success(
    merged_fields: Mapping[str, object], observation: object, admission: object
) -> bool:
    try:
        from .ctp_i10_oneshot_md_readonly import CtpI10OneShotMdObservation

        return (
            type(observation) is CtpI10OneShotMdObservation
            and type(admission.md_front) is str
            and observation.md_front_sha256
            == hashlib.sha256(admission.md_front.encode("utf-8")).hexdigest()
            and observation.account_fingerprint_sha256 == admission.account_fingerprint_sha256
            and observation.instrument_id == admission.instrument_id
            and observation.exchange_id == admission.exchange_id
            and observation.connection_generation > 0
            and observation.login_identity_state == "verified"
            and observation.subscription_acknowledged is True
            and observation.matching_tick_observed is True
            and observation.same_trading_day_observed is True
            and observation.client_stop_returned is True
            and observation.native_join_pending is False
            and observation.probe_session_closed is True
            and merged_fields["sdk_evidence_integrity"] == "valid"
            and merged_fields["sdk_login_disposition"] == "accepted"
            and merged_fields["adapter_evidence_integrity"] == "valid"
            and merged_fields["adapter_tick_classification"] == "tick_accepted"
            and merged_fields["adapter_accepted_tick_count"] == "one"
            and merged_fields["adapter_same_trading_day_observed"] is True
            and merged_fields["adapter_native_join_state"] == "completed"
        )
    except Exception:
        return False


def _run_i13_child_impl(argv: Optional[Sequence[str]] = None) -> int:
    arguments = tuple(sys.argv[1:] if argv is None else argv)
    if arguments:
        _emit_i13(_minimal_i13_receipt("rejected", "arguments_not_allowed", "arguments"))
        return 2
    deadline_monotonic = _read_child_deadline()
    if deadline_monotonic is None:
        _emit_i13(_minimal_i13_receipt("rejected", "supervisor_context_required", "arguments"))
        return 2
    if _i13_deadline_expired(deadline_monotonic):
        _emit_i13(_minimal_i13_receipt("incomplete", "child_deadline_exceeded", "arguments"))
        return 2
    source_root = Path(__file__).resolve().parents[1]
    try:
        verify_i13_source_identity(
            source_root,
            expected_manifest_sha256=os.environ.get(_I13_SOURCE_MANIFEST_ENV),
        )
        verify_i13_runtime_import_origins(source_root)
    except Exception:
        _emit_i13(_minimal_i13_receipt("rejected", "source_identity_unverified", "arguments"))
        return 2
    if not _has_supervised_i13_attempt_context():
        _emit_i13(_minimal_i13_receipt("rejected", "supervisor_context_required", "arguments"))
        return 2
    logging.disable(logging.CRITICAL)
    stage = "configuration"
    credential_resolver_invoked = False
    sdk_imported = False
    parent_precheck_binding_match = False
    selected_index: Optional[int] = None
    observation = None
    sdk_receipt = None
    events: tuple[I13MdEvent, ...] = ()
    close_state = "not_attempted"
    stop_returned: Optional[bool] = None
    join_pending: Optional[bool] = None
    session_closed: Optional[bool] = None
    login_state = "unavailable"
    progress = None
    reason = "configuration_rejected"
    status = "rejected"
    try:
        if I13_SDK_SOURCE_COMMIT != "c68bebe8631419801e7a24e13b98c42867df0beb":
            raise RuntimeError("i13_sdk_identity_mismatch")
        registry = iteration41_runtime_registry()
        effective = validate_runtime_config(ITERATION41_013_3_CTP_PRIVATE_RUNTIME_DIR, registry)
        require_effective_runtime_config_seal(effective, registry)
        from .ctp_i11_oneshot_md_diagnostic import _front_pair, _require_exact_child_scope

        _config, _registration, binding, private, front_pairs = _require_exact_child_scope(
            effective, registry
        )
        stage = "front_selection"
        from .ctp_i12_td_only_readonly import _child_recheck_precheck_binding

        child_binding = _child_recheck_precheck_binding()
        if _i13_deadline_expired(deadline_monotonic):
            raise TimeoutError("child_deadline_exceeded")
        if type(child_binding) is not I12FrontPrecheckBinding:
            raise ValueError("i13_front_precheck_binding_mismatch")
        parent_precheck_binding_match = True
        selected_index = child_binding.config_index
        if not 0 <= selected_index < len(front_pairs):
            raise ValueError("i13_front_precheck_binding_mismatch")
        selected_td, selected_md = _front_pair(front_pairs[selected_index])
        from .ctp_front_pair_probe import CtpConfiguredFrontPair

        selected_pair = CtpConfiguredFrontPair(md_front=selected_md, td_front=selected_td)
        admission, scope = binding._route(
            effective,
            registry,
            selected_front_pair=selected_pair,
            selected_config_index=selected_index,
        )
        if (admission.td_front, admission.md_front) != (selected_td, selected_md) or (
            admission.instrument_id,
            admission.exchange_id,
            admission.hedge_flag,
        ) != (private.instrument_id, private.exchange_id, private.hedge_flag):
            raise ValueError("i13_sealed_scope_mismatch")
        if _i13_deadline_expired(deadline_monotonic):
            raise TimeoutError("child_deadline_exceeded")

        from .ctp_artifact_provenance import (
            verify_ctp_i13_oneshot_md_diagnostic_artifact_provenance_for_fronts,
        )

        stage = "sdk_artifact"
        verify_i13_runtime_import_origins(source_root)
        with _trusted_i13_installed_capability_import_context(("bt_api_base", "bt_api_ctp")):
            _verify_i13_at_fixed_install_root(
                lambda: verify_ctp_i13_oneshot_md_diagnostic_artifact_provenance_for_fronts(
                    td_front=admission.td_front, md_front=admission.md_front
                )
            )
            if _i13_deadline_expired(deadline_monotonic):
                raise TimeoutError("child_deadline_exceeded")

            stage = "credentials"
            from .credential_resolver import (
                require_resolved_runtime_credentials_seal,
                resolve_runtime_credentials,
            )

            credential_resolver_invoked = True
            credentials = resolve_runtime_credentials(effective, registry, scope)
            require_resolved_runtime_credentials_seal(credentials, effective, registry, scope)
            from .ctp_simnow_readonly_runtime import _SealedCtpCredentialSource

            credential_source = _SealedCtpCredentialSource(credentials, effective, registry, scope)
            if _i13_deadline_expired(deadline_monotonic):
                raise TimeoutError("child_deadline_exceeded")

            stage = "market_data"
            sdk_module = __import__("bt_api_ctp.ctp.client", fromlist=["OneShotMdDiagnosticClient"])
            sdk_imported = True
            client_type = getattr(sdk_module, "OneShotMdDiagnosticClient")
            stop_receipt_type = getattr(sdk_module, "CtpNativeStopReceipt")
            from .ctp_artifact_provenance import (
                verify_ctp_i13_oneshot_md_diagnostic_artifact_provenance_for_fronts,
            )

            _verify_i13_at_fixed_install_root(
                lambda: verify_ctp_i13_oneshot_md_diagnostic_artifact_provenance_for_fronts(
                    td_front=admission.td_front, md_front=admission.md_front
                )
            )
            (
                observation,
                sdk_receipt,
                events,
                close_state,
                stop_returned,
                join_pending,
                session_closed,
                login_state,
            ) = _run_i13_market_adapter(
                admission=admission,
                credential_source=credential_source,
                client_type=client_type,
                stop_receipt_type=stop_receipt_type,
                deadline_monotonic=deadline_monotonic,
            )
        fields = _merge_receipt_fields(
            sdk_receipt,
            events,
            observation=observation,
            close_state=close_state,
            client_stop_returned=stop_returned,
            native_join_pending=join_pending,
            probe_session_closed=session_closed,
            parent_precheck_binding_match=parent_precheck_binding_match,
            credential_resolver_invoked=credential_resolver_invoked,
            sdk_imported=sdk_imported,
            source_identity_verified=True,
            selected_pair_index=selected_index,
            status="incomplete",
            reason="adapter_observation_incomplete",
            stage="market_data",
        )
        if join_pending is True:
            status, reason = "incomplete", "native_join_pending"
        elif login_state == "identity_unverified":
            status, reason = "incomplete", "identity_unverified"
        elif _child_success(fields, observation, admission):
            status, reason = "diagnostic_complete", "matching_tick_observed"
        elif _i13_deadline_expired(deadline_monotonic):
            status, reason = "incomplete", "child_deadline_exceeded"
        fields["status"] = status
        fields["reason"] = reason
        _emit_i13(fields)
        return 0 if status == "diagnostic_complete" else 3 if reason == "native_join_pending" else 2
    except Exception as error:
        safe_reason = (
            "child_deadline_exceeded"
            if _i13_deadline_expired(deadline_monotonic)
            else "sdk_artifact_rejected"
            if stage == "sdk_artifact"
            else "credential_rejected"
            if stage == "credentials"
            else "front_precheck_failed"
            if stage == "front_selection"
            else "market_probe_failed"
            if stage == "market_data"
            else "configuration_rejected"
        )
        progress = _safe_adapter_progress(error)
        merged_fields = _merge_receipt_fields(
            sdk_receipt,
            events,
            observation=observation,
            progress=progress,
            close_state=close_state,
            client_stop_returned=getattr(error, "client_stop_returned", stop_returned),
            native_join_pending=(
                True
                if getattr(error, "close_state", None) == "native_join_pending"
                else join_pending
            ),
            probe_session_closed=session_closed,
            parent_precheck_binding_match=parent_precheck_binding_match,
            credential_resolver_invoked=credential_resolver_invoked,
            sdk_imported=sdk_imported,
            source_identity_verified=True,
            selected_pair_index=selected_index,
            status="incomplete" if stage == "market_data" else "rejected",
            reason=safe_reason,
            stage=stage,
        )
        if merged_fields["native_join_pending"] is True:
            merged_fields["close_state"] = "native_join_pending"
            merged_fields["adapter_native_join_state"] = "pending_observed"
            merged_fields["status"] = "incomplete"
            merged_fields["reason"] = "native_join_pending"
        _emit_i13(merged_fields)
        return 3 if merged_fields["reason"] == "native_join_pending" else 2


def _run_i13_child_entry() -> int:
    return _run_i13_child_impl(())


def _is_current_process_in_i13_job() -> bool:
    if os.name != "nt":
        return False
    raw_handle = os.environ.pop(_I13_JOB_HANDLE_ENV, None)
    if (
        type(raw_handle) is not str
        or not raw_handle.isdecimal()
        or len(raw_handle) > 20
        or int(raw_handle) <= 0
    ):
        return False
    handle = ctypes.c_void_p(int(raw_handle))
    kernel32 = None
    try:
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.GetCurrentProcess.argtypes = ()
        kernel32.GetCurrentProcess.restype = ctypes.c_void_p
        is_process_in_job = kernel32.IsProcessInJob
        is_process_in_job.argtypes = (
            ctypes.c_void_p,
            ctypes.c_void_p,
            ctypes.POINTER(ctypes.c_int),
        )
        is_process_in_job.restype = ctypes.c_int
        in_job = ctypes.c_int()
        return bool(
            is_process_in_job(kernel32.GetCurrentProcess(), handle, ctypes.byref(in_job))
            and in_job.value != 0
        )
    except Exception:
        return False
    finally:
        if kernel32 is not None:
            try:
                kernel32.CloseHandle.argtypes = (ctypes.c_void_p,)
                kernel32.CloseHandle.restype = ctypes.c_int
                kernel32.CloseHandle(handle)
            except Exception:
                pass


def _has_supervised_i13_attempt_context() -> bool:
    if not _is_current_process_in_i13_job():
        return False
    try:
        return PersistentI13OneShotAttemptLatch().is_tripped() is True
    except Exception:
        return False


def supervise_i13_md_child() -> I13DiagnosticReport:
    """Programmatic unregistered candidate; deliberately absent from inventory/CLI."""

    return _supervise_i13_child()


__all__ = [
    "I13_CHILD_RECEIPT_SCHEMA",
    "I13DiagnosticReport",
    "I13_LATCH_PATH",
    "I13_SDK_SOURCE_COMMIT",
    "parse_i13_child_receipt",
    "supervise_i13_md_child",
]
