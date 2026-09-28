"""Unregistered I11 one-shot MD diagnostic with a fixed Windows Job worker.

I11 is deliberately distinct from I10: the parent requires a successful,
credential-free check of the sealed configured front pairs before it reserves
the I11-only attempt latch. The child then reloads and reseals the 013_3
simulation/sandbox config, repeats configured-front selection, verifies the
exact I10 SDK artifact before credentials and again for the selected pair,
and calls the I10 read-only MD adapter. No trading API is dispatched.
The fixed-venv artifact pin Job runs before the persistent marker; a later
child pin failure is fail-closed and still consumes that one-shot marker.

The child receipt contains only fixed categories and positively confirmed
booleans. Unknown callback progress remains null. The parent accepts success
only when both the exact receipt and the Windows Job exit/empty evidence agree.
The one-shot guarantee covers this supported operator entry only; it is not a
same-user security sandbox and cannot stop code running as the same user from
reading credentials or invoking the SDK outside this entry.
"""

from __future__ import annotations

import ctypes
import hashlib
import importlib
import json
import logging
import os
import stat
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Mapping, Optional, Sequence

from .ctp_i11_attempt_latch import (
    I11_LATCH_PATH,
    I11_REUSED_I10_WHEEL_SHA256,
    I11_SDK_SOURCE_COMMIT,
    PersistentI11OneShotAttemptLatch,
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
from .errors import PRESET_POLICY_VIOLATION, RuntimeConfigError
from .inventory import (
    ITERATION41_013_3_CTP_PRIVATE_RUNTIME_DIR,
    ITERATION41_013_3_CTP_PRIVATE_RUNTIME_ID,
    iteration41_runtime_registry,
)
from .registry import require_effective_runtime_config_seal, validate_runtime_config


_EXPECTED_I10_SDK_SOURCE_COMMIT = "a6253a58b1ebca11f58c8836fbed757d0daf7582"
_EXPECTED_I10_WHEEL_SHA256 = "e81bd7fcba8f0aaf823af9efcca565622a55842ed3bce970994f483f4f3188c4"
_I11_RUNTIME_ROOT = Path(r"D:\temp\i10-runtime-env-20260925")
_I11_INTERPRETER = _I11_RUNTIME_ROOT / "Scripts" / "python.exe"
_I11_WHEEL_A_ROOT = Path(r"D:\temp\i10-final-wheel-repro-20260925\artifacts\a")
_I11_BASE_PYTHON_ROOT = Path(r"C:\anaconda3")
_I11_JOB_HANDLE_ENV = "bt_i11_parent_job_handle"
_I11_PARENT_CONFIG_DIGEST_ENV = "BT_I11_EXPECTED_CONFIG_DIGEST"
_I11_PARENT_SELECTED_INDEX_ENV = "BT_I11_EXPECTED_SELECTED_INDEX"
_I11_CHILD_ENTRY_SOURCE = (
    "from backtrader_runtime.ctp_i11_oneshot_md_diagnostic import "
    "_run_child_entry; raise SystemExit(_run_child_entry())"
)
_I11_TOTAL_DEADLINE_SECONDS = 45.0
_I11_MARKET_DEADLINE_SECONDS = 15.0
_I11_TERMINATION_GRACE_SECONDS = 5.0
_I11_MAX_STDOUT_BYTES = 16 * 1024
_I11_RETAINED_JOB_CONTROL: object | None = None

_STATUSES = ("diagnostic_complete", "incomplete", "rejected")
_REASONS = (
    "arguments_not_allowed",
    "child_diagnostic_incomplete",
    "child_diagnostic_rejected",
    "configuration_rejected",
    "credential_rejected",
    "front_precheck_failed",
    "front_selection_rejected",
    "i11_latch_unavailable",
    "i11_runtime_unavailable",
    "i11_supervisor_failed",
    "i11_supervisor_result_invalid",
    "matching_tick_observed",
    "market_observation_incomplete",
    "market_probe_rejected",
    "native_join_pending",
    "parent_completion_evidence_missing",
    "prior_attempt_or_poisoned_latch",
    "runtime_policy_rejected",
    "sdk_artifact_rejected",
    "sdk_artifact_unavailable",
    "supervisor_context_required",
)
_STAGES = (
    "arguments",
    "configuration",
    "credentials",
    "front_selection",
    "market_data",
    "sdk_artifact",
)
_LOGIN_STATES = ("verified", "identity_unverified", "unavailable")
_CLOSE_STATES = (
    "unavailable",
    "not_started",
    "verified_closed",
    "stop_returned",
    "stop_failed",
    "native_stop_method_unknown",
    "native_stop_method_invalid",
    "native_stop_receipt_unknown",
    "native_stop_receipt_inconsistent",
    "native_stop_incomplete",
    "native_join_pending",
    "native_join_state_unknown",
)
_ZERO_OR_UNAVAILABLE = ("zero", "unavailable")

_ARTIFACT_PREFLIGHT_SCHEMA = ValueFreeReceiptSchema(
    enum_fields={
        "reason": ("artifact_rejected", "artifact_verified"),
        "status": ("rejected", "verified"),
    },
    nullable_enum_fields={},
    bool_fields=("credential_resolver_invoked", "native_join_pending", "sdk_imported"),
)

I11_CHILD_RECEIPT_SCHEMA = ValueFreeReceiptSchema(
    enum_fields={
        "close_state": _CLOSE_STATES,
        "login_identity_state": _LOGIN_STATES,
        "reason": _REASONS,
        "settlement_writes": _ZERO_OR_UNAVAILABLE,
        "stage": _STAGES,
        "status": _STATUSES,
        "trading_writes": _ZERO_OR_UNAVAILABLE,
    },
    nullable_enum_fields={
        "selected_pair_index": ("unavailable",) + tuple(f"pair_{index}" for index in range(8))
    },
    bool_fields=(
        "account_ready",
        "credential_resolver_invoked",
        "effective_config_digest_match",
        "market_login_ready",
        "order_submission_authorized",
        "sdk_imported",
        "trading_ready",
    ),
    nullable_bool_fields=(
        "client_stop_returned",
        "matching_tick_observed",
        "native_join_pending",
        "probe_session_closed",
        "same_trading_day_observed",
        "subscription_acknowledged",
    ),
)


@dataclass(frozen=True)
class I11DiagnosticReport:
    """Value-free parent report, with precheck, child and OS evidence separated."""

    status: str
    reason: str
    attempt_reserved: bool
    front_precheck: Optional[Mapping[str, object]]
    supervised: Optional[SupervisedResult]
    artifact_pin_verified: Optional[bool] = None
    artifact_job_containment: str = "not_started"

    def as_public_dict(self) -> dict[str, object]:
        receipt = (
            None
            if self.supervised is None
            else _exact_i11_child_receipt(self.supervised.sdk_receipt)
        )
        evidence = (
            _empty_evidence("not_started")
            if self.supervised is None
            else self.supervised.process_evidence
        )
        return {
            "attempt_reserved": self.attempt_reserved is True,
            "artifact_pin_precheck": {
                "job_containment": self.artifact_job_containment
                if self.artifact_job_containment
                in {"not_started", "unavailable", "uncertain", "verified"}
                else "unavailable",
                "verified": _nullable_bool(self.artifact_pin_verified),
            },
            "front_precheck": _public_front_precheck(self.front_precheck),
            "process_evidence": _safe_process_evidence(evidence),
            "reason": self.reason if self.reason in _REASONS else "runtime_policy_rejected",
            "sdk_receipt": receipt,
            "same_user_bypass_isolated": False,
            "scope": "supported_operator_entry_only",
            "status": self.status if self.status in _REPORT_STATUSES else "rejected",
        }


_REPORT_STATUSES = frozenset(
    {"diagnostic_complete", "incomplete", "latched", "rejected", "supervisor_error"}
)


def _emit_i11(
    *,
    status: str,
    reason: str,
    stage: str,
    close_state: str = "not_started",
    login_identity_state: str = "unavailable",
    credential_resolver_invoked: bool = False,
    effective_config_digest_match: bool = False,
    sdk_imported: bool = False,
    selected_pair_index: Optional[int] = None,
    client_stop_returned: Optional[bool] = None,
    matching_tick_observed: Optional[bool] = None,
    native_join_pending: Optional[bool] = None,
    probe_session_closed: Optional[bool] = None,
    same_trading_day_observed: Optional[bool] = None,
    subscription_acknowledged: Optional[bool] = None,
) -> None:
    payload: dict[str, object] = {
        "account_ready": False,
        "client_stop_returned": _nullable_bool(client_stop_returned),
        "close_state": close_state if close_state in _CLOSE_STATES else "unavailable",
        "credential_resolver_invoked": credential_resolver_invoked is True,
        "effective_config_digest_match": effective_config_digest_match is True,
        "login_identity_state": (
            login_identity_state if login_identity_state in _LOGIN_STATES else "unavailable"
        ),
        "market_login_ready": False,
        "matching_tick_observed": _nullable_bool(matching_tick_observed),
        "native_join_pending": _nullable_bool(native_join_pending),
        "order_submission_authorized": False,
        "probe_session_closed": _nullable_bool(probe_session_closed),
        "reason": reason if reason in _REASONS else "runtime_policy_rejected",
        "same_trading_day_observed": _nullable_bool(same_trading_day_observed),
        "selected_pair_index": (
            f"pair_{selected_pair_index}"
            if type(selected_pair_index) is int and 0 <= selected_pair_index < 8
            else "unavailable"
        ),
        "sdk_imported": sdk_imported is True,
        "settlement_writes": "zero",
        "stage": stage if stage in _STAGES else "configuration",
        "status": status if status in _STATUSES else "rejected",
        "subscription_acknowledged": _nullable_bool(subscription_acknowledged),
        "trading_ready": False,
        "trading_writes": "zero",
    }
    sys.stdout.write(json.dumps(payload, sort_keys=True, separators=(",", ":")) + "\n")
    sys.stdout.flush()


def _nullable_bool(value: object) -> Optional[bool]:
    return value if type(value) is bool else None


def parse_i11_child_receipt(raw: bytes) -> Optional[Mapping[str, object]]:
    """Parse one exact I11 value-free child receipt."""

    return parse_single_json_receipt(raw, I11_CHILD_RECEIPT_SCHEMA)


def _empty_evidence(containment: str) -> ProcessEvidence:
    return ProcessEvidence(False, False, False, None, None, False, None, None, containment)


def _safe_process_evidence(evidence: object) -> dict[str, object]:
    if type(evidence) is not ProcessEvidence:
        evidence = _empty_evidence("unavailable")
    return {
        "containment": evidence.containment
        if evidence.containment
        in {"latched", "not_started", "unavailable", "uncertain", "verified"}
        else "unavailable",
        "job_assignment_observed": evidence.job_assignment_observed is True,
        "job_empty_observed": _nullable_bool(evidence.job_empty_observed),
        "job_termination_call_succeeded": _nullable_bool(evidence.job_termination_call_succeeded),
        "job_termination_requested": evidence.job_termination_requested is True,
        "process_created": evidence.process_created is True,
        "process_exit_code": (
            evidence.process_exit_code if type(evidence.process_exit_code) is int else None
        ),
        "process_exit_observed": _nullable_bool(evidence.process_exit_observed),
        "process_resumed": evidence.process_resumed is True,
    }


def _safe_front_precheck(value: Optional[Mapping[str, object]]) -> dict[str, object]:
    if value is None:
        return {
            "configured_pair_count": 0,
            "pairs": [],
            "reachable_pair_count": 0,
            "selected_config_index": None,
            "status": "not_run",
        }
    count = value.get("configured_pair_count")
    pairs = value.get("pairs")
    selected = value.get("selected_config_index")
    status = value.get("status")
    if (
        type(count) is not int
        or not 0 <= count <= 8
        or type(pairs) not in (tuple, list)
        or len(pairs) != count
    ):
        return {
            "configured_pair_count": 0,
            "pairs": [],
            "reachable_pair_count": 0,
            "selected_config_index": None,
            "status": "rejected",
        }
    projected_pairs = []
    reachable = 0
    for index, item in enumerate(pairs):
        if type(item) is dict:
            pair = item
        else:
            try:
                pair = item.as_public_dict()
            except Exception:
                pair = None
        if (
            type(pair) is not dict
            or type(pair.get("config_index")) is not int
            or pair.get("config_index") != index
            or type(pair.get("md_connected_count")) is not int
            or type(pair.get("md_sample_count")) is not int
            or type(pair.get("td_connected_count")) is not int
            or type(pair.get("td_sample_count")) is not int
            or pair.get("md_sample_count") not in (0, 3)
            or pair.get("td_sample_count") not in (0, 3)
            or not 0 <= pair.get("md_connected_count") <= pair.get("md_sample_count")
            or not 0 <= pair.get("td_connected_count") <= pair.get("td_sample_count")
        ):
            return {
                "configured_pair_count": 0,
                "pairs": [],
                "reachable_pair_count": 0,
                "selected_config_index": None,
                "status": "rejected",
            }
        md_count = pair["md_sample_count"]
        td_count = pair["td_sample_count"]
        md_connected = pair["md_connected_count"]
        td_connected = pair["td_connected_count"]
        expected_status = (
            "unavailable"
            if md_count == 0 or td_count == 0
            else "reachable"
            if md_connected == 3 and td_connected == 3
            else "partial"
            if md_connected or td_connected
            else "unreachable"
        )
        if pair.get("status") != expected_status:
            return {
                "configured_pair_count": 0,
                "pairs": [],
                "reachable_pair_count": 0,
                "selected_config_index": None,
                "status": "rejected",
            }
        # Rebuild from an exact allow-list; never reflect extra keys from an
        # injected or future result object such as ``front`` or ``account``.
        projected_pairs.append(
            {
                "config_index": index,
                "md_connected_count": md_connected,
                "md_sample_count": md_count,
                "status": expected_status,
                "td_connected_count": td_connected,
                "td_sample_count": td_count,
            }
        )
        reachable += expected_status == "reachable"
    if type(status) is not str or status not in {"selected", "no_pair_reachable", "rejected"}:
        status = "rejected"
    if status in {"selected", "no_pair_reachable"} and any(
        pair["md_sample_count"] != 3 or pair["td_sample_count"] != 3 for pair in projected_pairs
    ):
        status = "rejected"
    if status == "selected":
        if (
            type(selected) is not int
            or not 0 <= selected < count
            or projected_pairs[selected]["status"] != "reachable"
            or reachable < 1
        ):
            status = "rejected"
            selected = None
    else:
        if status == "no_pair_reachable" and reachable:
            status = "rejected"
        selected = None
    return {
        "configured_pair_count": count,
        "pairs": projected_pairs,
        "reachable_pair_count": reachable,
        "selected_config_index": selected,
        "status": status,
    }


def _public_front_precheck(value: Optional[Mapping[str, object]]) -> dict[str, object]:
    safe = _safe_front_precheck(value)
    return {
        "configured_pair_count": safe["configured_pair_count"],
        "pairs": safe["pairs"],
        "precheck_selected_config_index": safe["selected_config_index"],
        "reachable_pair_count": safe["reachable_pair_count"],
        "status": safe["status"],
    }


def _concrete_path(path: Path, *, directory: bool) -> bool:
    if not path.is_absolute():
        return False
    parts = path.parts
    if not parts:
        return False
    current = Path(parts[0])
    for index, part in enumerate(parts[1:], start=1):
        current = current / part
        try:
            info = os.lstat(current)
        except OSError:
            return False
        if stat.S_ISLNK(info.st_mode) or bool(getattr(info, "st_file_attributes", 0) & 0x400):
            return False
        should_be_directory = index < len(parts) - 1 or directory
        if should_be_directory and not stat.S_ISDIR(info.st_mode):
            return False
        if not should_be_directory and not stat.S_ISREG(info.st_mode):
            return False
    return True


def _valid_config_digest(value: object) -> bool:
    return (
        type(value) is str
        and len(value) == 64
        and all(character in "0123456789abcdef" for character in value)
    )


def _fixed_i11_child_command(
    *, expected_config_index: int, expected_config_digest: str
) -> Optional[FixedChildCommand]:
    """Return only the code-owned I10-pinned interpreter on Windows."""

    if (
        os.name != "nt"
        or I11_SDK_SOURCE_COMMIT != _EXPECTED_I10_SDK_SOURCE_COMMIT
        or I11_REUSED_I10_WHEEL_SHA256 != _EXPECTED_I10_WHEEL_SHA256
        or type(expected_config_index) is not int
        or not 0 <= expected_config_index < 8
        or not _valid_config_digest(expected_config_digest)
    ):
        return None
    if (
        not _concrete_path(_I11_RUNTIME_ROOT, directory=True)
        or not _concrete_path(_I11_INTERPRETER, directory=False)
        or not _concrete_path(_I11_RUNTIME_ROOT / "pyvenv.cfg", directory=False)
        or not _concrete_path(_I11_WHEEL_A_ROOT, directory=True)
    ):
        return None
    try:
        venv_config = (_I11_RUNTIME_ROOT / "pyvenv.cfg").read_text(encoding="utf-8")
    except (OSError, UnicodeError):
        return None
    normalized = {line.strip().casefold() for line in venv_config.splitlines()}
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
    env = {
        "SYSTEMROOT": system_root,
        "WINDIR": system_root,
        "PATH": ";".join(
            (
                str(_I11_INTERPRETER.parent),
                str(_I11_BASE_PYTHON_ROOT),
                str(Path(system_root) / "System32"),
            )
        ),
        "TEMP": temp_dir,
        "TMP": temp_dir,
        "PYTHONNOUSERSITE": "1",
        "PYTHONDONTWRITEBYTECODE": "1",
        "PYTHONUNBUFFERED": "1",
        "PYTHONUTF8": "1",
        _I11_PARENT_CONFIG_DIGEST_ENV: expected_config_digest,
        _I11_PARENT_SELECTED_INDEX_ENV: str(expected_config_index),
    }
    try:
        return FixedChildCommand(
            (str(_I11_INTERPRETER), "-c", _I11_CHILD_ENTRY_SOURCE),
            Path(__file__).resolve().parents[1],
            env,
            job_handle_env_name=_I11_JOB_HANDLE_ENV,
        )
    except (OSError, TypeError, ValueError):
        return None


def _fixed_i11_artifact_preflight_command(
    worker_command: FixedChildCommand,
) -> Optional[FixedChildCommand]:
    """Build a fixed-venv pin verifier that imports no CTP SDK module."""

    source_root = str(worker_command.cwd)
    code = (
        "import json, sys\n"
        f"sys.path.insert(0, {source_root!r})\n"
        "payload = {'credential_resolver_invoked': False, 'native_join_pending': False, "
        "'reason': 'artifact_rejected', 'sdk_imported': False, 'status': 'rejected'}\n"
        "try:\n"
        "    from backtrader_runtime.ctp_artifact_provenance import "
        "CTP_I10_REPRODUCED_WHEEL_SHA256, "
        "verify_ctp_i10_oneshot_md_diagnostic_artifact_provenance_for_fronts\n"
        "    from backtrader_runtime.ctp_i11_attempt_latch import "
        "I11_REUSED_I10_WHEEL_SHA256, I11_SDK_SOURCE_COMMIT\n"
        f"    if I11_SDK_SOURCE_COMMIT != {_EXPECTED_I10_SDK_SOURCE_COMMIT!r}: raise RuntimeError()\n"
        f"    if I11_REUSED_I10_WHEEL_SHA256 != {_EXPECTED_I10_WHEEL_SHA256!r}: raise RuntimeError()\n"
        f"    if CTP_I10_REPRODUCED_WHEEL_SHA256 != {_EXPECTED_I10_WHEEL_SHA256!r}: raise RuntimeError()\n"
        "    verify_ctp_i10_oneshot_md_diagnostic_artifact_provenance_for_fronts("
        "td_front='tcp://127.0.0.1:10130', md_front='tcp://127.0.0.1:10131')\n"
        "    payload.update(reason='artifact_verified', status='verified')\n"
        "except Exception:\n"
        "    pass\n"
        "sys.stdout.write(json.dumps(payload, sort_keys=True, separators=(',', ':')) + '\\n')\n"
        "raise SystemExit(0 if payload['status'] == 'verified' else 2)\n"
    )
    try:
        environment = {
            key: value
            for key, value in worker_command.env.items()
            if key not in {_I11_PARENT_CONFIG_DIGEST_ENV, _I11_PARENT_SELECTED_INDEX_ENV}
        }
        return FixedChildCommand(
            (str(_I11_INTERPRETER), "-I", "-B", "-c", code),
            worker_command.cwd,
            environment,
        )
    except (OSError, TypeError, ValueError):
        return None


class _ArtifactPreflightLatch:
    """Process-local guard for the harmless metadata-only pin verifier Job."""

    def __init__(self) -> None:
        self._tripped = False

    def is_tripped(self) -> bool:
        return self._tripped

    def trip(self, _reason: str) -> bool:
        self._tripped = True
        return True


def _parse_artifact_preflight_receipt(raw: bytes) -> Optional[Mapping[str, object]]:
    return parse_single_json_receipt(raw, _ARTIFACT_PREFLIGHT_SCHEMA)


def _artifact_preflight_succeeded(result: object) -> bool:
    if type(result) is not SupervisedResult:
        return False
    receipt = result.sdk_receipt
    evidence = result.process_evidence
    try:
        valid_receipt = (
            type(receipt) is dict
            and _parse_artifact_preflight_receipt(
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
        and receipt["native_join_pending"] is False
        and type(evidence) is ProcessEvidence
        and result.status == "child_exited"
        and result.reason == "child_process_exited"
        and evidence.process_created is True
        and evidence.job_assignment_observed is True
        and evidence.process_resumed is True
        and evidence.process_exit_observed is True
        and type(evidence.process_exit_code) is int
        and evidence.process_exit_code == 0
        and evidence.job_termination_requested is False
        and evidence.job_termination_call_succeeded is None
        and evidence.job_empty_observed is True
        and evidence.containment == "verified"
        and result.retained_control is None
    )


def _supervise_i11_child(
    *,
    registry: object | None = None,
    effective: object | None = None,
    front_check: Optional[Callable[[object, object], object]] = None,
    latch_factory: Optional[Callable[[Path], FailClosedLatch]] = None,
    command_factory: Optional[Callable[..., Optional[FixedChildCommand]]] = None,
    runner: Optional[Callable[..., SupervisedResult]] = None,
) -> I11DiagnosticReport:
    """Credential-free precheck first; reserve I11 only before fixed child launch."""

    global _I11_RETAINED_JOB_CONTROL
    if os.name != "nt":
        return I11DiagnosticReport("supervisor_error", "i11_runtime_unavailable", False, None, None)
    active_registry = registry or iteration41_runtime_registry()
    try:
        active_effective = effective or validate_runtime_config(
            ITERATION41_013_3_CTP_PRIVATE_RUNTIME_DIR, active_registry
        )
        require_effective_runtime_config_seal(active_effective, active_registry)
    except Exception:
        return I11DiagnosticReport("rejected", "configuration_rejected", False, None, None)
    active_front_check = front_check
    if active_front_check is None:
        from .ctp_configured_front_check import check_configured_ctp_fronts

        active_front_check = check_configured_ctp_fronts
    try:
        checked = active_front_check(active_effective, active_registry)
        precheck = {
            "configured_pair_count": checked.configured_pair_count,
            "pairs": checked.pairs,
            "selected_config_index": checked.selected_config_index,
            "status": checked.status,
        }
    except Exception:
        return I11DiagnosticReport("rejected", "front_precheck_failed", False, None, None)
    safe_precheck = _safe_front_precheck(precheck)
    if safe_precheck["status"] != "selected" or safe_precheck["reachable_pair_count"] < 1:
        return I11DiagnosticReport("rejected", "front_precheck_failed", False, safe_precheck, None)

    try:
        _, _, _, _, configured_pairs = _require_exact_child_scope(active_effective, active_registry)
    except Exception:
        return I11DiagnosticReport("rejected", "configuration_rejected", False, safe_precheck, None)
    selected_index = safe_precheck["selected_config_index"]
    if (
        type(selected_index) is not int
        or not 0 <= selected_index < len(configured_pairs)
        or safe_precheck["configured_pair_count"] != len(configured_pairs)
    ):
        return I11DiagnosticReport(
            "rejected", "front_selection_rejected", False, safe_precheck, None
        )
    config_digest = getattr(active_effective, "effective_digest", None)
    if not _valid_config_digest(config_digest):
        return I11DiagnosticReport(
            "rejected",
            "configuration_rejected",
            False,
            safe_precheck,
            None,
        )
    command_builder = command_factory or _fixed_i11_child_command
    try:
        command = command_builder(
            expected_config_index=selected_index,
            expected_config_digest=config_digest,
        )
        if command is None:
            return I11DiagnosticReport(
                "supervisor_error", "i11_runtime_unavailable", False, safe_precheck, None
            )
        artifact_command = _fixed_i11_artifact_preflight_command(command)
        if artifact_command is None:
            return I11DiagnosticReport(
                "supervisor_error",
                "i11_runtime_unavailable",
                False,
                safe_precheck,
                None,
                artifact_pin_verified=False,
                artifact_job_containment="not_started",
            )
    except Exception:
        return I11DiagnosticReport(
            "supervisor_error",
            "i11_runtime_unavailable",
            False,
            safe_precheck,
            None,
            artifact_pin_verified=False,
            artifact_job_containment="not_started",
        )
    active_runner = runner or run_readonly_child
    try:
        artifact_result = active_runner(
            artifact_command,
            _parse_artifact_preflight_receipt,
            receipt_schema=_ARTIFACT_PREFLIGHT_SCHEMA,
            fail_closed_latch=_ArtifactPreflightLatch(),
            deadline_seconds=10.0,
            max_stdout_bytes=4096,
            termination_grace_seconds=2.0,
        )
    except Exception:
        return I11DiagnosticReport(
            "supervisor_error",
            "i11_supervisor_failed",
            False,
            safe_precheck,
            None,
            artifact_pin_verified=False,
            artifact_job_containment="unavailable",
        )
    if type(artifact_result) is SupervisedResult and artifact_result.retained_control is not None:
        _I11_RETAINED_JOB_CONTROL = artifact_result.retained_control
    artifact_containment = (
        artifact_result.process_evidence.containment
        if type(artifact_result) is SupervisedResult
        and type(artifact_result.process_evidence) is ProcessEvidence
        else "unavailable"
    )
    if not _artifact_preflight_succeeded(artifact_result):
        reason = (
            "sdk_artifact_rejected"
            if artifact_containment == "verified"
            else "i11_supervisor_failed"
        )
        return I11DiagnosticReport(
            "rejected" if reason == "sdk_artifact_rejected" else "supervisor_error",
            reason,
            False,
            safe_precheck,
            artifact_result if type(artifact_result) is SupervisedResult else None,
            artifact_pin_verified=False,
            artifact_job_containment=artifact_containment,
        )

    make_latch = latch_factory or PersistentI11OneShotAttemptLatch
    try:
        latch = make_latch(I11_LATCH_PATH)
        if not callable(getattr(latch, "begin_attempt", None)):
            return I11DiagnosticReport(
                "supervisor_error",
                "i11_latch_unavailable",
                False,
                safe_precheck,
                None,
                artifact_pin_verified=True,
                artifact_job_containment=artifact_containment,
            )
        if latch.begin_attempt() is not True:
            return I11DiagnosticReport(
                "latched",
                "prior_attempt_or_poisoned_latch",
                False,
                safe_precheck,
                None,
                artifact_pin_verified=True,
                artifact_job_containment=artifact_containment,
            )
    except Exception:
        return I11DiagnosticReport(
            "supervisor_error",
            "i11_latch_unavailable",
            False,
            safe_precheck,
            None,
            artifact_pin_verified=True,
            artifact_job_containment=artifact_containment,
        )

    try:
        result = active_runner(
            command,
            parse_i11_child_receipt,
            receipt_schema=I11_CHILD_RECEIPT_SCHEMA,
            fail_closed_latch=latch,
            deadline_seconds=_I11_TOTAL_DEADLINE_SECONDS,
            max_stdout_bytes=_I11_MAX_STDOUT_BYTES,
            termination_grace_seconds=_I11_TERMINATION_GRACE_SECONDS,
        )
    except Exception:
        return I11DiagnosticReport(
            "supervisor_error",
            "i11_supervisor_failed",
            True,
            safe_precheck,
            SupervisedResult(
                "supervisor_error",
                "i11_supervisor_failed",
                None,
                _empty_evidence("unavailable"),
            ),
            artifact_pin_verified=True,
            artifact_job_containment=artifact_containment,
        )
    if type(result) is not SupervisedResult:
        return I11DiagnosticReport(
            "supervisor_error",
            "i11_supervisor_result_invalid",
            True,
            safe_precheck,
            SupervisedResult(
                "supervisor_error",
                "i11_supervisor_result_invalid",
                None,
                _empty_evidence("unavailable"),
            ),
            artifact_pin_verified=True,
            artifact_job_containment=artifact_containment,
        )
    if result.retained_control is not None:
        _I11_RETAINED_JOB_CONTROL = result.retained_control
    report = _parent_report(result, safe_precheck, selected_index)
    return I11DiagnosticReport(
        report.status,
        report.reason,
        report.attempt_reserved,
        report.front_precheck,
        report.supervised,
        artifact_pin_verified=True,
        artifact_job_containment=artifact_containment,
    )


def _parent_report(
    result: SupervisedResult,
    precheck: Optional[Mapping[str, object]],
    expected_config_index: Optional[int] = None,
) -> I11DiagnosticReport:
    receipt = _exact_i11_child_receipt(result.sdk_receipt)
    if _parent_confirms_i11_diagnostic(result, expected_config_index):
        return I11DiagnosticReport(
            "diagnostic_complete", "matching_tick_observed", True, precheck, result
        )
    if receipt is not None:
        if receipt["native_join_pending"] is True:
            return I11DiagnosticReport("incomplete", "native_join_pending", True, precheck, result)
        if receipt["status"] == "diagnostic_complete":
            return I11DiagnosticReport(
                "incomplete", "parent_completion_evidence_missing", True, precheck, result
            )
        status = "incomplete" if receipt["status"] == "incomplete" else "rejected"
        return I11DiagnosticReport(status, "child_diagnostic_rejected", True, precheck, result)
    status_map = {
        "latched": ("latched", "prior_attempt_or_poisoned_latch"),
        "pending_native_join": ("incomplete", "native_join_pending"),
        "timed_out": ("incomplete", "child_diagnostic_incomplete"),
    }
    status, reason = status_map.get(
        result.status,
        ("supervisor_error", "i11_supervisor_failed"),
    )
    return I11DiagnosticReport(status, reason, True, precheck, result)


def _exact_i11_child_receipt(value: object) -> Optional[dict[str, object]]:
    if type(value) is not dict:
        return None
    try:
        encoded = (json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")
    except (TypeError, ValueError, UnicodeError):
        return None
    parsed = parse_i11_child_receipt(encoded)
    if type(parsed) is not dict or parsed != value:
        return None
    return parsed


def _parent_confirms_i11_diagnostic(result: object, expected_config_index: Optional[int]) -> bool:
    if type(result) is not SupervisedResult:
        return False
    receipt = _exact_i11_child_receipt(result.sdk_receipt)
    evidence = result.process_evidence
    if receipt is None or type(evidence) is not ProcessEvidence:
        return False
    expected_fields = (
        set(I11_CHILD_RECEIPT_SCHEMA.enum_fields)
        | set(I11_CHILD_RECEIPT_SCHEMA.nullable_enum_fields)
        | set(I11_CHILD_RECEIPT_SCHEMA.bool_fields)
        | set(I11_CHILD_RECEIPT_SCHEMA.nullable_bool_fields)
    )
    if (
        set(receipt) != expected_fields
        or receipt["status"] != "diagnostic_complete"
        or receipt["reason"] != "matching_tick_observed"
        or receipt["stage"] != "market_data"
        or receipt["close_state"] != "verified_closed"
        or type(expected_config_index) is not int
        or not 0 <= expected_config_index < 8
        or receipt["selected_pair_index"] != f"pair_{expected_config_index}"
        or receipt["effective_config_digest_match"] is not True
        or receipt["login_identity_state"] not in {"verified", "identity_unverified"}
        or receipt["credential_resolver_invoked"] is not True
        or receipt["sdk_imported"] is not True
        or receipt["trading_writes"] != "zero"
        or receipt["settlement_writes"] != "zero"
        or any(
            receipt[name] is not True
            for name in (
                "client_stop_returned",
                "matching_tick_observed",
                "probe_session_closed",
                "same_trading_day_observed",
                "subscription_acknowledged",
            )
        )
        or any(
            receipt[name] is not False
            for name in (
                "account_ready",
                "market_login_ready",
                "native_join_pending",
                "order_submission_authorized",
                "trading_ready",
            )
        )
    ):
        return False
    return (
        result.status == "child_exited"
        and result.reason == "child_process_exited"
        and evidence.process_created is True
        and evidence.job_assignment_observed is True
        and evidence.process_resumed is True
        and evidence.process_exit_observed is True
        and type(evidence.process_exit_code) is int
        and evidence.process_exit_code == 0
        and evidence.job_termination_requested is False
        and evidence.job_termination_call_succeeded is None
        and evidence.job_empty_observed is True
        and evidence.containment == "verified"
        and result.retained_control is None
    )


def _front_pair(front_pair: object) -> tuple[str, str]:
    if not isinstance(front_pair, Mapping):
        raise RuntimeConfigError(
            PRESET_POLICY_VIOLATION,
            "the sealed front pair is invalid",
            field_path="ctp.front_pairs",
            reason="front_selection_rejected",
        )
    td_front = front_pair.get("td_front")
    md_front = front_pair.get("md_front")
    if type(td_front) is not str or type(md_front) is not str:
        raise RuntimeConfigError(
            PRESET_POLICY_VIOLATION,
            "the sealed front pair is invalid",
            field_path="ctp.front_pairs",
            reason="front_selection_rejected",
        )
    return td_front, md_front


def _require_exact_child_scope(
    effective: object, registry: object
) -> tuple[Any, Any, Any, Any, tuple[Any, ...]]:
    from .ctp_simnow_operator import CtpSimNowConfigReadOnlyBinding
    from .registry import RuntimeProfile

    try:
        config = effective.config
        registration = registry.require_runtime_dir(config.strategy_dir)
        profile = registration.profile_for("simulation", "sandbox")
        facts = (
            type(profile) is RuntimeProfile
            and profile.mode == "simulation"
            and profile.preset == "sandbox"
            and profile.allowed_parameter_keys == ()
            and profile.allowed_secrets_refs == ("config_yaml",)
            and profile.available_capabilities == ()
            and profile.approval_receipt_digest is None
            and profile.runner_module is None
            and profile.runner_entrypoint == "run_runtime"
            and profile.capability_modules == ()
            and profile.offline_managed_execution is False
            and profile.sandbox_write_policy == "deny"
        )
    except Exception:
        raise RuntimeConfigError(
            PRESET_POLICY_VIOLATION,
            "the exact I11 sandbox profile is required",
            field_path="runtime.preset",
            reason="runtime_policy_rejected",
        ) from None
    if (
        config.strategy_dir != ITERATION41_013_3_CTP_PRIVATE_RUNTIME_DIR
        or registration is not effective.registration
        or registration.runtime_id != ITERATION41_013_3_CTP_PRIVATE_RUNTIME_ID
        or registration.runtime_dir != ITERATION41_013_3_CTP_PRIVATE_RUNTIME_DIR
        or effective.mode != "simulation"
        or effective.preset != "sandbox"
        or effective.profile is not profile
        or not facts
    ):
        raise RuntimeConfigError(
            PRESET_POLICY_VIOLATION,
            "the exact I11 sandbox profile is required",
            field_path="runtime.preset",
            reason="runtime_policy_rejected",
        )
    binding = registry.require_ctp_simnow_readonly_binding(registration.runtime_id)
    if type(binding) is not CtpSimNowConfigReadOnlyBinding:
        raise RuntimeConfigError(
            PRESET_POLICY_VIOLATION,
            "the exact config-driven read-only binding is required",
            field_path="runtime.preset",
            reason="runtime_policy_rejected",
        )
    private, bound_registration, front_pairs = binding._sealed_private_config(effective, registry)
    if (
        bound_registration is not registration
        or type(front_pairs) is not tuple
        or not 1 <= len(front_pairs) <= 8
        or type(getattr(private, "instrument_id", None)) is not str
        or type(getattr(private, "exchange_id", None)) is not str
        or type(getattr(private, "hedge_flag", None)) is not str
    ):
        raise RuntimeConfigError(
            PRESET_POLICY_VIOLATION,
            "the sealed I11 private CTP scope is invalid",
            field_path="ctp.front_pairs",
            reason="front_selection_rejected",
        )
    return config, registration, binding, private, front_pairs


def _safe_i10_progress(value: object) -> dict[str, object]:
    try:
        from .ctp_i10_oneshot_md_readonly import CtpI10OneShotMdProgressEvidence

        if type(value) is not CtpI10OneShotMdProgressEvidence:
            raise TypeError
        login_state = value.login_identity_state
        if login_state not in {"verified", "identity_unverified"}:
            login_state = "unavailable"
        return {
            "login_identity_state": login_state,
            "matching_tick_observed": _nullable_bool(value.matching_tick_observed),
            "same_trading_day_observed": _nullable_bool(value.same_trading_day_observed),
            "subscription_acknowledged": _nullable_bool(value.subscription_acknowledged),
        }
    except Exception:
        return {
            "login_identity_state": "unavailable",
            "matching_tick_observed": None,
            "same_trading_day_observed": None,
            "subscription_acknowledged": None,
        }


def _run_i11_child_impl(argv: Optional[Sequence[str]] = None) -> int:
    """Private child body. Direct invocations fail unless in Job + I11 latch."""

    arguments = tuple(sys.argv[1:] if argv is None else argv)
    if arguments:
        _emit_i11(status="rejected", reason="arguments_not_allowed", stage="arguments")
        return 2
    if not _has_supervised_i11_attempt_context():
        _emit_i11(status="rejected", reason="supervisor_context_required", stage="arguments")
        return 2
    expected_config_digest = os.environ.pop(_I11_PARENT_CONFIG_DIGEST_ENV, None)
    expected_index_text = os.environ.pop(_I11_PARENT_SELECTED_INDEX_ENV, None)
    if (
        not _valid_config_digest(expected_config_digest)
        or type(expected_index_text) is not str
        or not expected_index_text.isdecimal()
        or len(expected_index_text) > 1
    ):
        _emit_i11(
            status="rejected",
            reason="configuration_rejected",
            stage="configuration",
        )
        return 2
    expected_config_index = int(expected_index_text)
    if not 0 <= expected_config_index < 8:
        _emit_i11(
            status="rejected",
            reason="configuration_rejected",
            stage="configuration",
        )
        return 2
    logging.disable(logging.CRITICAL)
    stage = "configuration"
    credential_resolver_invoked = False
    sdk_imported = False
    effective_config_digest_match = False
    selected_config_index: Optional[int] = None
    try:
        if (
            I11_SDK_SOURCE_COMMIT != _EXPECTED_I10_SDK_SOURCE_COMMIT
            or I11_REUSED_I10_WHEEL_SHA256 != _EXPECTED_I10_WHEEL_SHA256
        ):
            raise RuntimeError("i11_sdk_identity_mismatch")
        registry = iteration41_runtime_registry()
        effective = validate_runtime_config(ITERATION41_013_3_CTP_PRIVATE_RUNTIME_DIR, registry)
        require_effective_runtime_config_seal(effective, registry)
        effective_config_digest_match = (
            getattr(effective, "effective_digest", None) == expected_config_digest
        )
        if not effective_config_digest_match:
            raise RuntimeConfigError(
                PRESET_POLICY_VIOLATION,
                "the child config does not match the sealed parent config",
                field_path="runtime.config",
                reason="configuration_rejected",
            )
        _config, registration, binding, private, front_pairs = _require_exact_child_scope(
            effective, registry
        )

        from .capability_imports import trusted_installed_capability_import_context
        from .ctp_artifact_provenance import (
            verify_ctp_i10_oneshot_md_diagnostic_artifact_provenance_for_fronts,
        )

        stage = "sdk_artifact"
        with trusted_installed_capability_import_context(("bt_api_base", "bt_api_ctp")):
            first_td, first_md = _front_pair(front_pairs[0])
            verify_ctp_i10_oneshot_md_diagnostic_artifact_provenance_for_fronts(
                td_front=first_td, md_front=first_md
            )

            stage = "front_selection"
            from .ctp_configured_front_check import check_configured_ctp_fronts
            from .ctp_front_pair_probe import CtpConfiguredFrontPair

            checked = check_configured_ctp_fronts(effective, registry)
            if (
                checked.succeeded is not True
                or type(checked.selected_config_index) is not int
                or not 0 <= checked.selected_config_index < len(front_pairs)
            ):
                raise RuntimeConfigError(
                    PRESET_POLICY_VIOLATION,
                    "the sealed configured front set has no reachable pair",
                    field_path="ctp.front_pairs",
                    reason="front_selection_rejected",
                )
            selected_index = checked.selected_config_index
            selected_config_index = selected_index
            if selected_index != expected_config_index:
                raise RuntimeConfigError(
                    PRESET_POLICY_VIOLATION,
                    "the child selected pair differs from the parent precheck",
                    field_path="ctp.front_pairs",
                    reason="front_selection_rejected",
                )
            selected_td, selected_md = _front_pair(front_pairs[selected_index])
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
                raise RuntimeConfigError(
                    PRESET_POLICY_VIOLATION,
                    "the selected MD-only scope does not match sealed config",
                    field_path="ctp.front_pairs",
                    reason="front_selection_rejected",
                )
            stage = "sdk_artifact"
            verify_ctp_i10_oneshot_md_diagnostic_artifact_provenance_for_fronts(
                td_front=admission.td_front, md_front=admission.md_front
            )

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

            stage = "market_data"
            sdk_module = importlib.import_module("bt_api_ctp.ctp.client")
            sdk_imported = True
            client_type = getattr(sdk_module, "OneShotMdDiagnosticClient")
            stop_receipt_type = getattr(sdk_module, "CtpNativeStopReceipt")
            from .ctp_i10_oneshot_md_readonly import (
                probe_i10_oneshot_md_readonly,
            )

            observation = probe_i10_oneshot_md_readonly(
                admission=admission,
                credential_source=credential_source,
                client_type=client_type,
                stop_receipt_type=stop_receipt_type,
                timeout_seconds=_I11_MARKET_DEADLINE_SECONDS,
            )

        if not _valid_success_observation(observation, admission):
            from .ctp_i10_oneshot_md_readonly import CtpI10OneShotMdObservation

            exact_observation = type(observation) is CtpI10OneShotMdObservation
            join_pending = observation.native_join_pending is True if exact_observation else None
            stop_returned = observation.client_stop_returned is True if exact_observation else None
            session_closed = observation.probe_session_closed if exact_observation else None
            close_state = (
                "verified_closed"
                if session_closed is True
                else "native_join_pending"
                if join_pending is True
                else "stop_returned"
                if stop_returned is True
                else "unavailable"
            )
            _emit_i11(
                status="incomplete",
                reason="market_observation_incomplete",
                stage="market_data",
                close_state=close_state,
                login_identity_state=(
                    observation.login_identity_state if exact_observation else "unavailable"
                ),
                credential_resolver_invoked=credential_resolver_invoked,
                effective_config_digest_match=effective_config_digest_match,
                sdk_imported=sdk_imported,
                selected_pair_index=selected_config_index,
                client_stop_returned=stop_returned,
                matching_tick_observed=(
                    observation.matching_tick_observed if exact_observation else None
                ),
                native_join_pending=join_pending,
                probe_session_closed=session_closed,
                same_trading_day_observed=(
                    observation.same_trading_day_observed if exact_observation else None
                ),
                subscription_acknowledged=(
                    observation.subscription_acknowledged if exact_observation else None
                ),
            )
            return 3 if join_pending is True else 2
        _emit_i11(
            status="diagnostic_complete",
            reason="matching_tick_observed",
            stage="market_data",
            close_state="verified_closed",
            login_identity_state=observation.login_identity_state,
            credential_resolver_invoked=True,
            effective_config_digest_match=effective_config_digest_match,
            sdk_imported=True,
            selected_pair_index=selected_config_index,
            client_stop_returned=True,
            matching_tick_observed=True,
            native_join_pending=False,
            probe_session_closed=True,
            same_trading_day_observed=True,
            subscription_acknowledged=True,
        )
        return 0
    except Exception as error:
        reason = _reason_for_i11_exception(error, stage)
        close_state = (
            getattr(error, "close_state", "not_started")
            if stage == "market_data"
            else "not_started"
        )
        close_state = close_state if close_state in _CLOSE_STATES else "unavailable"
        progress = _safe_i10_progress(getattr(error, "i10_progress_evidence", None))
        pending = True if close_state == "native_join_pending" else None
        closed = (
            True
            if close_state == "stop_returned"
            and getattr(error, "client_stop_returned", None) is True
            else None
        )
        status = "incomplete" if stage == "market_data" else "rejected"
        if pending is True:
            reason = "native_join_pending"
        _emit_i11(
            status=status,
            reason=reason,
            stage=stage,
            close_state=close_state,
            login_identity_state=progress["login_identity_state"],
            credential_resolver_invoked=credential_resolver_invoked,
            effective_config_digest_match=effective_config_digest_match,
            sdk_imported=sdk_imported,
            selected_pair_index=selected_config_index,
            client_stop_returned=getattr(error, "client_stop_returned", None),
            matching_tick_observed=progress["matching_tick_observed"],
            native_join_pending=pending,
            probe_session_closed=closed,
            same_trading_day_observed=progress["same_trading_day_observed"],
            subscription_acknowledged=progress["subscription_acknowledged"],
        )
        return 3 if pending is True else 2


def _valid_success_observation(observation: object, admission: object) -> bool:
    try:
        from .ctp_i10_oneshot_md_readonly import CtpI10OneShotMdObservation

        return (
            type(observation) is CtpI10OneShotMdObservation
            and type(admission.md_front) is str
            and type(observation.md_front_sha256) is str
            and observation.md_front_sha256
            == hashlib.sha256(admission.md_front.encode("utf-8")).hexdigest()
            and type(observation.account_fingerprint_sha256) is str
            and observation.account_fingerprint_sha256 == admission.account_fingerprint_sha256
            and type(observation.instrument_id) is str
            and observation.instrument_id == admission.instrument_id
            and type(observation.exchange_id) is str
            and observation.exchange_id == admission.exchange_id
            and observation.login_identity_state in {"verified", "identity_unverified"}
            and type(observation.connection_generation) is int
            and observation.connection_generation > 0
            and observation.subscription_acknowledged is True
            and observation.matching_tick_observed is True
            and observation.same_trading_day_observed is True
            and observation.client_stop_returned is True
            and observation.native_join_pending is False
            and observation.probe_session_closed is True
            and observation.account_ready is False
            and observation.trading_ready is False
            and observation.order_submission_authorized is False
            and type(observation.trading_writes) is int
            and observation.trading_writes == 0
            and type(observation.settlement_writes) is int
            and observation.settlement_writes == 0
        )
    except Exception:
        return False


def _reason_for_i11_exception(error: BaseException, stage: str) -> str:
    if stage == "sdk_artifact":
        return (
            "sdk_artifact_unavailable"
            if getattr(error, "reason", None) == "artifact_pin_unavailable"
            else "sdk_artifact_rejected"
        )
    if stage == "credentials":
        return "credential_rejected"
    if isinstance(error, RuntimeConfigError):
        return {
            "configuration": "configuration_rejected",
            "front_selection": "front_selection_rejected",
        }.get(stage, "runtime_policy_rejected")
    return "market_probe_rejected" if stage == "market_data" else "runtime_policy_rejected"


def _is_current_process_in_i11_job() -> bool:
    if os.name != "nt":
        return False
    raw_handle = os.environ.pop(_I11_JOB_HANDLE_ENV, None)
    if (
        type(raw_handle) is not str
        or not raw_handle.isdecimal()
        or len(raw_handle) > 20
        or int(raw_handle) <= 0
    ):
        return False
    job_handle = ctypes.c_void_p(int(raw_handle))
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
            is_process_in_job(kernel32.GetCurrentProcess(), job_handle, ctypes.byref(in_job))
            and in_job.value != 0
        )
    except Exception:
        return False
    finally:
        if kernel32 is not None:
            try:
                kernel32.CloseHandle.argtypes = (ctypes.c_void_p,)
                kernel32.CloseHandle.restype = ctypes.c_int
                kernel32.CloseHandle(job_handle)
            except Exception:
                pass


def _has_supervised_i11_attempt_context() -> bool:
    if not _is_current_process_in_i11_job():
        return False
    try:
        return PersistentI11OneShotAttemptLatch(I11_LATCH_PATH).is_tripped() is True
    except Exception:
        return False


def _run_child_entry() -> int:
    return _run_i11_child_impl(())


def _parent_payload(report: I11DiagnosticReport) -> dict[str, object]:
    payload = report.as_public_dict()
    return payload


def main(argv: Optional[Sequence[str]] = None) -> int:
    """Run one explicit I11 attempt; this candidate is not CLI/registry wired."""

    arguments = tuple(sys.argv[1:] if argv is None else argv)
    if arguments:
        report = I11DiagnosticReport("rejected", "arguments_not_allowed", False, None, None)
    else:
        report = _supervise_i11_child()
    sys.stdout.write(json.dumps(_parent_payload(report), sort_keys=True) + "\n")
    sys.stdout.flush()
    if report.status == "diagnostic_complete":
        return 0
    return 3 if report.reason == "native_join_pending" else 2


__all__ = [
    "I11_CHILD_RECEIPT_SCHEMA",
    "I11DiagnosticReport",
    "main",
    "parse_i11_child_receipt",
]
