"""Unregistered I12 one-shot TD-only CTP read-only candidate.

This candidate is intentionally separate from the registered runtime and the
I11 MD composition.  Its parent performs a credential-free precheck; the
selector probes both MD and TD endpoints with bounded unauthenticated TCP and
chooses a configured whole pair, then the fixed child rechecks only that same
pair after fresh sealing the runtime configuration.  MD probe results are
transport evidence only: the native/API path is TD-only and never constructs
MdClient, logs in to MD, or subscribes to market data.  The child verifies the
independent I12 TD installed-artifact pin before resolving credentials for one
TD session.  It has no settlement, order, or cancel call path.
"""

from __future__ import annotations

import ctypes
import hashlib
import hmac
import json
import logging
import os
import re
import stat
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any, Callable, Mapping, Optional

from .capability_imports import trusted_installed_capability_import_context
from .ctp_artifact_provenance import (
    CtpArtifactProvenanceError,
    verify_ctp_i12_td_only_readonly_artifact_provenance_for_fronts,
)
from .ctp_front_pair_probe import (
    CtpConfiguredFrontPair,
    CtpFrontPairProbeError,
    CtpFrontPairSelection,
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
from .registry import (
    require_effective_runtime_config_seal,
    validate_runtime_config,
)

if TYPE_CHECKING:
    from .ctp_sdk_readonly import CtpSdkReadOnlyCloseEvidence


I12_SDK_SOURCE_COMMIT = "a6253a58b1ebca11f58c8836fbed757d0daf7582"
I12_REUSED_I10_WHEEL_SHA256 = "e81bd7fcba8f0aaf823af9efcca565622a55842ed3bce970994f483f4f3188c4"
_I12_EXPECTED_BASE_ARTIFACT = (
    "bt_api_base",
    "bt_api_base",
    "0.15.5",
    "bt_api_base-0.15.5-py3-none-any.whl",
    "1c1129444d8659f4dfe7b72f716872a63dddf13c1c935865e1d2568800d0d64d",
    "47994f991fee3266e62fb368fe167dc1f188eceecfddac6ccc06dad2604e9762",
)
_I12_EXPECTED_CTP_ARTIFACT = (
    "bt_api_ctp",
    "bt_api_ctp",
    "2.0.3+iteration41.i10",
    "bt_api_ctp-2.0.3+iteration41.i10-cp311-cp311-win_amd64.whl",
    I12_REUSED_I10_WHEEL_SHA256,
    "c0cd1f19a6af3f2bab0fc98042b5042e620565b67751bae362bf5d697649d673",
)
_I12_RUNTIME_ROOT = Path(r"D:\temp\i10-runtime-env-20260925")
_I12_INTERPRETER = _I12_RUNTIME_ROOT / "Scripts" / "python.exe"
_I12_WHEEL_A_ROOT = Path(r"D:\temp\i10-final-wheel-repro-20260925\artifacts\a")
_I12_BASE_PYTHON_ROOT = Path(r"C:\anaconda3")
_I12_JOB_HANDLE_ENV = "bt_i12_parent_job_handle"
_I12_PRECHECK_INDEX_ENV = "bt_i12_precheck_index"
_I12_PRECHECK_BINDING_ENV = "bt_i12_precheck_binding_sha256"
_I12_CHILD_ENTRY_SOURCE = (
    "from backtrader_runtime.ctp_i12_td_only_readonly import "
    "_run_child_entry; raise SystemExit(_run_child_entry())"
)
_I12_TOTAL_DEADLINE_SECONDS = 90.0
_I12_TERMINATION_GRACE_SECONDS = 5.0
_I12_MAX_STDOUT_BYTES = 32 * 1024
_I12_FRONT_PROBE_TIMEOUT_SECONDS = 3.0
_I12_FRONT_PROBE_MAX_PAIRS = 8
_I12_FRONT_PROBE_SAMPLES = 3
_I12_RETAINED_JOB_CONTROL: Optional[object] = None
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_QUERY_FIELD_NAMES = {
    "account": "query_account_state",
    "positions": "query_positions_state",
    "orders": "query_orders_state",
    "trades": "query_trades_state",
    "instruments": "query_instruments_state",
    "margin_rates": "query_margin_rate_state",
    "commission_rates": "query_commission_rate_state",
}

_I12_STATUS_VALUES = ("td_readonly_complete", "incomplete", "rejected")
_I12_REASON_VALUES = (
    "arguments_not_allowed",
    "child_diagnostic_incomplete",
    "child_diagnostic_rejected",
    "child_process_exited",
    "configuration_rejected",
    "credential_rejected",
    "front_precheck_rejected",
    "i12_runtime_or_latch_unavailable",
    "i12_supervisor_failed",
    "invalid_child_receipt",
    "native_join_pending",
    "parent_completion_evidence_missing",
    "prior_attempt_or_poisoned_latch",
    "query_bundle_unverified",
    "route_binding_rejected",
    "runtime_policy_rejected",
    "sdk_artifact_rejected",
    "session_close_unknown",
    "session_open_rejected",
    "supervisor_context_required",
    "td_identity_rejected",
    "td_readonly_query_bundle_closed",
    "windows_required",
    "child_deadline_exceeded",
    "stdout_limit_exceeded",
)
_I12_STAGE_VALUES = (
    "arguments",
    "configuration",
    "front_precheck",
    "route_binding",
    "sdk_artifact",
    "credentials",
    "td_session",
)
_I12_LOGIN_VALUES = ("not_observed", "verified", "rejected")
_I12_QUERY_VALUES = ("unverified", "complete")
_I12_RATE_SCOPE_VALUES = ("unobserved", "exact", "unverified")
_I12_CLOSE_VALUES = ("not_attempted", "complete", "native_join_pending", "unknown")
_I12_WRITE_VALUES = ("zero", "unavailable")

I12_CHILD_RECEIPT_SCHEMA = ValueFreeReceiptSchema(
    enum_fields={
        **dict.fromkeys(_QUERY_FIELD_NAMES.values(), _I12_QUERY_VALUES),
        "close_state": _I12_CLOSE_VALUES,
        "commission_rate_exchange_scope": _I12_RATE_SCOPE_VALUES,
        "login_state": _I12_LOGIN_VALUES,
        "margin_rate_exchange_scope": _I12_RATE_SCOPE_VALUES,
        "reason": _I12_REASON_VALUES,
        "stage": _I12_STAGE_VALUES,
        "status": _I12_STATUS_VALUES,
        "write_counts_state": _I12_WRITE_VALUES,
    },
    nullable_enum_fields={},
    bool_fields=(
        "account_ready",
        "order_submission_authorized",
        "query_bundle_complete",
        "query_values_redacted",
        "settlement_confirmation_called",
        "trading_ready",
    ),
    nullable_bool_fields=(
        "client_stop_returned",
        "join_completed",
        "join_required",
        "native_join_pending",
        "native_release_complete",
    ),
)
_I12_ARTIFACT_PREFLIGHT_SCHEMA = ValueFreeReceiptSchema(
    enum_fields={
        "reason": ("artifact_rejected", "artifact_verified"),
        "status": ("rejected", "verified"),
    },
    nullable_enum_fields={},
    bool_fields=("credential_resolver_invoked", "native_join_pending", "sdk_imported"),
    nullable_bool_fields=(),
)


@dataclass(frozen=True)
class I12FrontPrecheckBinding:
    """Safe parent-to-child binding for one freshly selected sealed pair."""

    config_index: int
    binding_sha256: str = field(repr=False)

    def __post_init__(self) -> None:
        if (
            type(self.config_index) is not int
            or not 0 <= self.config_index < 8
            or type(self.binding_sha256) is not str
            or not _SHA256_RE.fullmatch(self.binding_sha256)
        ):
            raise ValueError("i12_front_binding_invalid")


@dataclass(frozen=True)
class I12TdOnlySessionEvidence:
    """Categorical, value-free evidence from one TD query/close attempt."""

    status: str
    reason: str
    login_state: str
    query_bundle_complete: bool
    margin_rate_exchange_scope: str
    commission_rate_exchange_scope: str
    write_counts_state: str
    close_evidence: CtpSdkReadOnlyCloseEvidence

    def __post_init__(self) -> None:
        from .ctp_sdk_readonly import CtpSdkReadOnlyCloseEvidence

        if self.status not in _I12_STATUS_VALUES or self.reason not in _I12_REASON_VALUES:
            raise ValueError("i12_session_evidence_invalid")
        if self.login_state not in _I12_LOGIN_VALUES:
            raise ValueError("i12_session_evidence_invalid")
        if type(self.query_bundle_complete) is not bool:
            raise ValueError("i12_session_evidence_invalid")
        if self.margin_rate_exchange_scope not in _I12_RATE_SCOPE_VALUES:
            raise ValueError("i12_session_evidence_invalid")
        if self.commission_rate_exchange_scope not in _I12_RATE_SCOPE_VALUES:
            raise ValueError("i12_session_evidence_invalid")
        if self.write_counts_state not in _I12_WRITE_VALUES:
            raise ValueError("i12_session_evidence_invalid")
        if type(self.close_evidence) is not CtpSdkReadOnlyCloseEvidence:
            raise ValueError("i12_session_evidence_invalid")
        if self.status == "td_readonly_complete" and not (
            self.reason == "td_readonly_query_bundle_closed"
            and self.login_state == "verified"
            and self.query_bundle_complete is True
            and self.margin_rate_exchange_scope in ("exact", "unverified")
            and self.commission_rate_exchange_scope in ("exact", "unverified")
            and self.write_counts_state == "zero"
            and self.close_evidence.verified_complete is True
        ):
            raise ValueError("i12_session_evidence_invalid")
        if self.reason == "native_join_pending" and not (
            self.status == "incomplete" and self.close_evidence.native_join_pending
        ):
            raise ValueError("i12_session_evidence_invalid")

    def as_child_fields(self, *, stage: str) -> dict[str, object]:
        query_state = "complete" if self.query_bundle_complete else "unverified"
        close = self.close_evidence
        return {
            **dict.fromkeys(_QUERY_FIELD_NAMES.values(), query_state),
            "account_ready": False,
            "close_state": (
                close.status if close.status in _I12_CLOSE_VALUES else "unknown"
            ),
            "commission_rate_exchange_scope": self.commission_rate_exchange_scope,
            "join_completed": _nullable_bool(close.join_completed),
            "join_required": _nullable_bool(close.join_required),
            "login_state": self.login_state,
            "margin_rate_exchange_scope": self.margin_rate_exchange_scope,
            "native_join_pending": (
                close.native_join_pending if close.status != "unknown" else None
            ),
            "native_release_complete": _nullable_bool(close.native_released),
            "order_submission_authorized": False,
            "query_bundle_complete": self.query_bundle_complete,
            "query_values_redacted": True,
            "reason": self.reason,
            "settlement_confirmation_called": False,
            "stage": stage,
            "status": self.status,
            "trading_ready": False,
            "write_counts_state": self.write_counts_state,
            "client_stop_returned": _nullable_bool(close.client_stop_returned),
        }


def _nullable_bool(value: object) -> Optional[bool]:
    return value if type(value) is bool else None


def _receipt_fields_complete(value: object) -> Optional[Mapping[str, object]]:
    if type(value) is not dict:
        return None
    try:
        encoded = (json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n").encode(
            "utf-8"
        )
    except (TypeError, ValueError, UnicodeError):
        return None
    parsed = parse_single_json_receipt(encoded, I12_CHILD_RECEIPT_SCHEMA)
    if type(parsed) is not dict or parsed != value:
        return None
    return parsed


def parse_i12_child_receipt(raw: bytes) -> Optional[Mapping[str, object]]:
    """Parse one duplicate-free receipt against the exact value-free schema."""

    return parse_single_json_receipt(raw, I12_CHILD_RECEIPT_SCHEMA)


def _front_binding_digest(
    *,
    effective_digest: str,
    registration_digest: str,
    config_index: int,
    md_front: str,
    td_front: str,
) -> I12FrontPrecheckBinding:
    if (
        type(effective_digest) is not str
        or not _SHA256_RE.fullmatch(effective_digest)
        or type(registration_digest) is not str
        or not _SHA256_RE.fullmatch(registration_digest)
        or type(config_index) is not int
        or not 0 <= config_index < 8
        or type(md_front) is not str
        or type(td_front) is not str
    ):
        raise ValueError("i12_front_binding_invalid")
    payload = {
        "schema": "ctp_i12_td_only_front_binding.v1",
        "effective_config_digest": effective_digest,
        "registration_digest": registration_digest,
        "config_index": config_index,
        "md_front_sha256": hashlib.sha256(md_front.encode("utf-8")).hexdigest(),
        "td_front_sha256": hashlib.sha256(td_front.encode("utf-8")).hexdigest(),
    }
    digest = hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    return I12FrontPrecheckBinding(config_index, digest)


def _candidate_front_pair(front_pair: object) -> tuple[str, str]:
    try:
        md_front = front_pair.get("md_front")
        td_front = front_pair.get("td_front")
    except Exception:
        md_front = td_front = None
    if type(td_front) is not str or type(md_front) is not str:
        raise RuntimeConfigError(
            PRESET_POLICY_VIOLATION,
            "the sealed CTP front pair is invalid",
            field_path="ctp.front_pairs",
            reason="ctp_simnow_preflight_front_selection_required",
        )
    return md_front, td_front


def _load_sealed_context() -> tuple[Any, Any, Any, Any, tuple[Any, ...]]:
    """Load a fresh exact 013_3 sandbox seal without resolving credentials."""

    registry = iteration41_runtime_registry()
    effective = validate_runtime_config(ITERATION41_013_3_CTP_PRIVATE_RUNTIME_DIR, registry)
    require_effective_runtime_config_seal(effective, registry)
    try:
        config = effective.config
        registration = registry.require_runtime_dir(config.strategy_dir)
        profile = registration.profile_for("simulation", "sandbox")
        binding = registry.require_ctp_simnow_readonly_binding(registration.runtime_id)
        if (
            registration is not effective.registration
            or registration.runtime_id != ITERATION41_013_3_CTP_PRIVATE_RUNTIME_ID
            or effective.mode != "simulation"
            or effective.preset != "sandbox"
            or effective.profile is not profile
            or profile.mode != "simulation"
            or profile.preset != "sandbox"
            or profile.allowed_parameter_keys != ()
            or profile.allowed_secrets_refs != ("config_yaml",)
            or profile.available_capabilities != ()
            or profile.approval_receipt_digest is not None
            or profile.runner_module is not None
            or profile.capability_modules != ()
            or profile.offline_managed_execution is not False
            or profile.sandbox_write_policy != "deny"
        ):
            raise ValueError("runtime_profile_mismatch")
        private, bound_registration, front_pairs = binding._sealed_private_config(
            effective, registry
        )
        if (
            bound_registration is not registration
            or type(front_pairs) is not tuple
            or not 1 <= len(front_pairs) <= 8
        ):
            raise ValueError("front_pair_set_invalid")
        if not callable(getattr(binding, "_route", None)):
            raise ValueError("runtime_binding_invalid")
    except Exception:
        raise RuntimeConfigError(
            PRESET_POLICY_VIOLATION,
            "the exact sealed CTP sandbox configuration was rejected",
            field_path="runtime.preset",
            reason="runtime_profile_mismatch",
        ) from None
    return effective, registry, binding, private, front_pairs


def _selection_index(selection: object, front_pairs: tuple[Any, ...]) -> int:
    if type(selection) is not CtpFrontPairSelection:
        raise ValueError("front_selection_invalid")
    index = selection.config_index
    if type(index) is not int or not 0 <= index < len(front_pairs):
        raise ValueError("front_selection_mismatch")
    try:
        selected = (selection.pair.md_front, selection.pair.td_front)
        configured = _candidate_front_pair(front_pairs[index])
    except Exception:
        raise ValueError("front_selection_invalid") from None
    if selected != configured:
        raise ValueError("front_selection_mismatch")
    return index


def _select_configured_front_pair(
    front_pairs: tuple[Any, ...], *, deadline_monotonic: Optional[float] = None
) -> CtpFrontPairSelection:
    """Credential-free selection from only the currently sealed candidates."""

    if deadline_monotonic is None:
        from .ctp_simnow_operator import _select_configured_front_pair as select_bound_pairs

        selection = select_bound_pairs(front_pairs)
    else:
        # The parent operation uses time.monotonic(), while the selector's
        # default clock is time.perf_counter(). Convert only the remaining
        # budget into that clock's domain so parallel endpoint jobs stay
        # available and the selector receives the same absolute cutoff.
        from .ctp_front_pair_probe import select_ctp_front_pair

        perf_started = time.perf_counter()
        monotonic_now = time.monotonic()
        selection_deadline = perf_started + (deadline_monotonic - monotonic_now)
        selection = select_ctp_front_pair(
            front_pairs,
            timeout_seconds=_I12_FRONT_PROBE_TIMEOUT_SECONDS,
            max_pairs=_I12_FRONT_PROBE_MAX_PAIRS,
            repeated_samples=_I12_FRONT_PROBE_SAMPLES,
            deadline_monotonic=selection_deadline,
        )
    _selection_index(selection, front_pairs)
    return selection


def _precheck_binding_for_selection(
    effective: Any,
    registry: Any,
    front_pairs: tuple[Any, ...],
    selection: object,
) -> I12FrontPrecheckBinding:
    index = _selection_index(selection, front_pairs)
    md_front, td_front = _candidate_front_pair(front_pairs[index])
    return _front_binding_digest(
        effective_digest=effective.effective_digest,
        registration_digest=effective.registration.digest,
        config_index=index,
        md_front=md_front,
        td_front=td_front,
    )


def _parent_credential_free_precheck(
    *, deadline_monotonic: Optional[float] = None
) -> I12FrontPrecheckBinding:
    effective, registry, _binding, _private, front_pairs = _load_sealed_context()
    if deadline_monotonic is not None and time.monotonic() >= deadline_monotonic:
        raise TimeoutError("i12_operation_deadline_exceeded")
    selection = _select_configured_front_pair(
        front_pairs, deadline_monotonic=deadline_monotonic
    )
    if deadline_monotonic is not None and time.monotonic() >= deadline_monotonic:
        raise TimeoutError("i12_operation_deadline_exceeded")
    return _precheck_binding_for_selection(effective, registry, front_pairs, selection)


def _child_recheck_precheck_binding() -> I12FrontPrecheckBinding:
    raw_index = os.environ.pop(_I12_PRECHECK_INDEX_ENV, None)
    expected_digest = os.environ.pop(_I12_PRECHECK_BINDING_ENV, None)
    if (
        type(raw_index) is not str
        or not raw_index.isdecimal()
        or len(raw_index) > 1
        or type(expected_digest) is not str
        or not _SHA256_RE.fullmatch(expected_digest)
    ):
        raise ValueError("front_precheck_binding_missing")
    index = int(raw_index)
    effective, _registry, _binding, _private, front_pairs = _load_sealed_context()
    if not 0 <= index < len(front_pairs):
        raise ValueError("front_precheck_binding_mismatch")
    pair = front_pairs[index]
    md_front, td_front = _candidate_front_pair(pair)

    # Probe only the parent's selected pair again.  The child never changes to
    # a different configured pair when transport observations have shifted.
    from .ctp_simnow_operator import _select_configured_front_pair as select_bound_pairs

    child_selection = select_bound_pairs((pair,))
    if (
        type(child_selection) is not CtpFrontPairSelection
        or child_selection.config_index != 0
        or (child_selection.pair.md_front, child_selection.pair.td_front)
        != (md_front, td_front)
    ):
        raise ValueError("front_precheck_binding_mismatch")
    current = _front_binding_digest(
        effective_digest=effective.effective_digest,
        registration_digest=effective.registration.digest,
        config_index=index,
        md_front=md_front,
        td_front=td_front,
    )
    if not hmac.compare_digest(current.binding_sha256, expected_digest):
        raise ValueError("front_precheck_binding_mismatch")
    return current


def _validate_bound_scope(
    private: Any,
    admission: Any,
    index: int,
    front_pairs: tuple[Any, ...],
) -> None:
    expected = (private.instrument_id, private.exchange_id, private.hedge_flag)
    admitted = (admission.instrument_id, admission.exchange_id, admission.hedge_flag)
    if admitted != expected or (admission.md_front, admission.td_front) != _candidate_front_pair(
        front_pairs[index]
    ):
        raise ValueError("sealed_scope_mismatch")


class _I12SealedCredentialSource:
    """Narrow credential view that revalidates the fresh config seal per read."""

    __slots__ = ("_credentials", "_effective", "_registry", "_scope")

    def __init__(self, credentials: Any, effective: Any, registry: Any, scope: Any) -> None:
        self._credentials = credentials
        self._effective = effective
        self._registry = registry
        self._scope = scope

    def __repr__(self) -> str:
        return "_I12SealedCredentialSource(credentials=<redacted>)"

    def require_credential(self, name: str) -> str:
        from .credential_resolver import (
            CTP_AUTHENTICATION_CREDENTIAL_KEYS,
            CredentialResolutionError,
            require_resolved_runtime_credentials_seal,
        )

        if type(name) is not str or name not in CTP_AUTHENTICATION_CREDENTIAL_KEYS:
            raise CredentialResolutionError(
                "credential_name_not_available", "the requested credential is unavailable"
            )
        require_resolved_runtime_credentials_seal(
            self._credentials, self._effective, self._registry, self._scope
        )
        try:
            value = self._credentials.require_credential(name)
        except Exception:
            raise CredentialResolutionError(
                "credential_unavailable", "the scoped credential is unavailable"
            ) from None
        if type(value) is not str or not value:
            raise CredentialResolutionError(
                "credential_unavailable", "the scoped credential is unavailable"
            )
        return value


def _unknown_close_evidence() -> Any:
    from .ctp_sdk_readonly import CtpSdkReadOnlyCloseEvidence

    return CtpSdkReadOnlyCloseEvidence("unknown")


def _snapshot_rate_scope(snapshot: Any, name: str) -> str:
    try:
        scope = dict(snapshot.rate_exchange_scopes)[name]
    except Exception:
        return "unobserved"
    return scope if scope in ("exact", "unverified") else "unobserved"


def _run_i12_td_only_session_candidate(
    session_factory: Any,
    request: Any,
) -> I12TdOnlySessionEvidence:
    """Run only the seven-query TD session and retain value-free close proof.

    ``session_factory`` is a private test seam.  The production composition
    supplies only ``CtpSdkReadOnlySessionFactory`` after the I10 installed
    artifact gate.  This function has no MD or trading-write call surface.
    """

    from .ctp_preflight import (
        REQUIRED_CTP_READ_ONLY_QUERIES,
        CtpReadOnlyQuerySnapshot,
        CtpReadOnlySessionIdentity,
        CtpReadOnlySessionRequest,
    )
    from .ctp_sdk_readonly import (
        CtpSdkReadOnlyCloseEvidence,
        CtpSdkReadOnlyError,
    )

    close_evidence = _unknown_close_evidence()
    session = None
    login_state = "not_observed"
    query_complete = False
    margin_scope = "unobserved"
    commission_scope = "unobserved"
    failure_reason = "session_open_rejected"
    if type(request) is not CtpReadOnlySessionRequest:
        return I12TdOnlySessionEvidence(
            "rejected",
            "runtime_policy_rejected",
            login_state,
            False,
            margin_scope,
            commission_scope,
            "unavailable",
            close_evidence,
        )
    try:
        session = session_factory.open_read_only(request)
        if session is None:
            raise CtpSdkReadOnlyError("session_open_failed")
        first_identity = session.read_identity()
        if (
            type(first_identity) is not CtpReadOnlySessionIdentity
            or first_identity.provider != request.provider
            or first_identity.environment != request.environment
            or not hmac.compare_digest(
                first_identity.account_fingerprint_sha256,
                request.account_fingerprint_sha256,
            )
        ):
            login_state = "rejected"
            failure_reason = "td_identity_rejected"
            raise CtpSdkReadOnlyError("session_identity_mismatch")
        login_state = "verified"
        snapshot = session.read_query_snapshot()
        if (
            type(snapshot) is not CtpReadOnlyQuerySnapshot
            or snapshot.identity != first_identity
            or snapshot.native_certificate_sha256 is None
            or {name for name, _digest in snapshot.query_digests}
            != set(REQUIRED_CTP_READ_ONLY_QUERIES)
            or len(snapshot.query_digests) != len(REQUIRED_CTP_READ_ONLY_QUERIES)
        ):
            failure_reason = "query_bundle_unverified"
            raise CtpSdkReadOnlyError("native_query_certificate_failed")
        margin_scope = _snapshot_rate_scope(snapshot, "margin_rates")
        commission_scope = _snapshot_rate_scope(snapshot, "commission_rates")
        final_identity = session.read_identity()
        if final_identity != first_identity:
            failure_reason = "td_identity_rejected"
            raise CtpSdkReadOnlyError("session_identity_changed")
        query_complete = True
    except CtpSdkReadOnlyError:
        if failure_reason == "session_open_rejected" and login_state == "verified":
            failure_reason = "query_bundle_unverified"
    except Exception:
        if login_state == "verified":
            failure_reason = "query_bundle_unverified"
    finally:
        if session is not None:
            try:
                candidate = session.close_read_only_with_evidence()
                if type(candidate) is CtpSdkReadOnlyCloseEvidence:
                    close_evidence = candidate
            except Exception:
                close_evidence = _unknown_close_evidence()

    if close_evidence.native_join_pending:
        status, reason = "incomplete", "native_join_pending"
    elif query_complete and close_evidence.verified_complete:
        status, reason = "td_readonly_complete", "td_readonly_query_bundle_closed"
    elif (close_evidence.status == "unknown" and session is not None) or query_complete:
        status, reason = "incomplete", "session_close_unknown"
    elif login_state == "verified":
        status, reason = "incomplete", failure_reason
    else:
        status, reason = "rejected", failure_reason

    return I12TdOnlySessionEvidence(
        status,
        reason,
        login_state,
        query_complete,
        margin_scope,
        commission_scope,
        "zero" if query_complete else "unavailable",
        close_evidence,
    )


def _emit_i12(fields: Mapping[str, object]) -> None:
    """Emit exactly one schema-constrained receipt and no raw child output."""

    payload = _receipt_fields_complete(dict(fields))
    if payload is None:
        payload = {
            **dict.fromkeys(_QUERY_FIELD_NAMES.values(), "unverified"),
            "account_ready": False,
            "close_state": "unknown",
            "commission_rate_exchange_scope": "unobserved",
            "join_completed": None,
            "join_required": None,
            "login_state": "not_observed",
            "margin_rate_exchange_scope": "unobserved",
            "native_join_pending": None,
            "native_release_complete": None,
            "order_submission_authorized": False,
            "query_bundle_complete": False,
            "query_values_redacted": True,
            "reason": "runtime_policy_rejected",
            "settlement_confirmation_called": False,
            "stage": "configuration",
            "status": "rejected",
            "trading_ready": False,
            "write_counts_state": "unavailable",
            "client_stop_returned": None,
        }
    sys.stdout.write(json.dumps(payload, sort_keys=True, separators=(",", ":")) + "\n")
    sys.stdout.flush()


def _run_diagnostic_impl() -> int:
    """Fixed TD-only child body; all gates precede secret resolution."""

    if tuple(sys.argv[1:]):
        _emit_i12(_initial_receipt(reason="arguments_not_allowed", stage="arguments"))
        return 2
    if not _has_supervised_i12_attempt_context():
        _emit_i12(_initial_receipt(reason="supervisor_context_required", stage="arguments"))
        return 2
    logging.disable(logging.CRITICAL)
    stage = "configuration"
    session_evidence: Optional[I12TdOnlySessionEvidence] = None
    try:
        if I12_SDK_SOURCE_COMMIT != "a6253a58b1ebca11f58c8836fbed757d0daf7582":
            raise RuntimeError("i12_sdk_source_mismatch")
        stage = "front_precheck"
        precheck = _child_recheck_precheck_binding()
        stage = "configuration"
        effective, registry, binding, private, front_pairs = _load_sealed_context()
        index = precheck.config_index
        if not 0 <= index < len(front_pairs):
            raise ValueError("fresh_seal_binding_mismatch")
        selected_pair = front_pairs[index]
        md_front, td_front = _candidate_front_pair(selected_pair)
        current_binding = _front_binding_digest(
            effective_digest=effective.effective_digest,
            registration_digest=effective.registration.digest,
            config_index=index,
            md_front=md_front,
            td_front=td_front,
        )
        if not hmac.compare_digest(
            current_binding.binding_sha256, precheck.binding_sha256
        ):
            raise ValueError("fresh_seal_binding_mismatch")
        stage = "sdk_artifact"
        with trusted_installed_capability_import_context(("bt_api_base", "bt_api_ctp")):
            verify_ctp_i12_td_only_readonly_artifact_provenance_for_fronts(
                td_front=td_front,
                md_front=md_front,
            )

            stage = "route_binding"
            from .ctp_sandbox_readonly_admission import (
                require_ctp_sandbox_readonly_runtime_contract,
            )

            selected_front_pair = CtpConfiguredFrontPair(
                md_front=md_front,
                td_front=td_front,
            )
            admission, credential_scope = binding._route(
                effective,
                registry,
                selected_front_pair=selected_front_pair,
                selected_config_index=index,
            )
            _validate_bound_scope(private, admission, index, front_pairs)
            admission = require_ctp_sandbox_readonly_runtime_contract(
                effective, registry, admission
            )

            stage = "credentials"
            from .credential_resolver import (
                require_resolved_runtime_credentials_seal,
                resolve_runtime_credentials,
            )

            credentials = resolve_runtime_credentials(effective, registry, credential_scope)
            require_resolved_runtime_credentials_seal(
                credentials, effective, registry, credential_scope
            )
            stage = "td_session"
            from .ctp_preflight import CTP_PROVIDER, CtpReadOnlySessionRequest
            from .ctp_sdk_readonly import (
                CtpSdkReadOnlyScope,
                CtpSdkReadOnlySessionFactory,
            )

            credential_source = _I12SealedCredentialSource(
                credentials, effective, registry, credential_scope
            )
            sdk_scope = CtpSdkReadOnlyScope(
                environment=admission.environment,
                sdk_profile=admission.sdk_profile,
                td_front=admission.td_front,
                md_front=admission.md_front,
                account_fingerprint_sha256=admission.account_fingerprint_sha256,
                instrument_id=admission.instrument_id,
                exchange_id=admission.exchange_id,
                hedge_flag=admission.hedge_flag,
            )
            session_factory = CtpSdkReadOnlySessionFactory(
                sdk_scope,
                credential_source,
                connect_timeout=15.0,
                query_timeout=5.0,
            )
            request = CtpReadOnlySessionRequest(
                provider=CTP_PROVIDER,
                environment=admission.environment,
                account_fingerprint_sha256=admission.account_fingerprint_sha256,
                valid_until=time.time() + admission.session_ttl_seconds,
            )
            session_evidence = _run_i12_td_only_session_candidate(session_factory, request)

        fields = (
            session_evidence.as_child_fields(stage=stage)
            if session_evidence is not None
            else _initial_receipt(reason="runtime_policy_rejected", stage=stage)
        )
        _emit_i12(fields)
        return 0 if session_evidence.status == "td_readonly_complete" else 3
    except Exception as error:
        reason = _safe_reason_for_exception(error, stage)
        fields = _initial_receipt(reason=reason, stage=stage)
        if session_evidence is not None:
            fields.update(session_evidence.as_child_fields(stage=stage))
        _emit_i12(fields)
        return 2


def _initial_receipt(*, reason: str, stage: str) -> dict[str, object]:
    safe_reason = reason if reason in _I12_REASON_VALUES else "runtime_policy_rejected"
    safe_stage = stage if stage in _I12_STAGE_VALUES else "configuration"
    return {
        **dict.fromkeys(_QUERY_FIELD_NAMES.values(), "unverified"),
        "account_ready": False,
        "close_state": "not_attempted",
        "commission_rate_exchange_scope": "unobserved",
        "join_completed": None,
        "join_required": None,
        "login_state": "not_observed",
        "margin_rate_exchange_scope": "unobserved",
        "native_join_pending": None,
        "native_release_complete": None,
        "order_submission_authorized": False,
        "query_bundle_complete": False,
        "query_values_redacted": True,
        "reason": safe_reason,
        "settlement_confirmation_called": False,
        "stage": safe_stage,
        "status": "rejected",
        "trading_ready": False,
        "write_counts_state": "unavailable",
        "client_stop_returned": None,
    }


def _safe_reason_for_exception(error: BaseException, stage: str) -> str:
    if isinstance(error, CtpArtifactProvenanceError):
        return "sdk_artifact_rejected"
    if isinstance(error, CtpFrontPairProbeError):
        return "front_precheck_rejected"
    if isinstance(error, RuntimeConfigError):
        if stage == "configuration":
            return "configuration_rejected"
        if stage == "route_binding":
            return "route_binding_rejected"
        if stage == "credentials":
            return "credential_rejected"
        return "runtime_policy_rejected"
    return {
        "front_precheck": "front_precheck_rejected",
        "route_binding": "route_binding_rejected",
        "sdk_artifact": "sdk_artifact_rejected",
        "credentials": "credential_rejected",
        "td_session": "session_open_rejected",
    }.get(stage, "runtime_policy_rejected")


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
        if stat.S_ISLNK(result.st_mode) or bool(
            getattr(result, "st_file_attributes", 0) & 0x400
        ):
            return False
        expected_directory = index < len(parts) - 1 or directory
        if expected_directory and not stat.S_ISDIR(result.st_mode):
            return False
        if not expected_directory and not stat.S_ISREG(result.st_mode):
            return False
    return True


def _fixed_i12_child_command(binding: I12FrontPrecheckBinding) -> Optional[FixedChildCommand]:
    """Return the fixed I12 command bound to the reviewed I10 isolated venv."""

    if os.name != "nt" or I12_SDK_SOURCE_COMMIT != "a6253a58b1ebca11f58c8836fbed757d0daf7582":
        return None
    if (
        not _is_concrete_path(_I12_RUNTIME_ROOT, directory=True)
        or not _is_concrete_path(_I12_INTERPRETER, directory=False)
        or not _is_concrete_path(_I12_RUNTIME_ROOT / "pyvenv.cfg", directory=False)
        or not _is_concrete_path(_I12_WHEEL_A_ROOT, directory=True)
    ):
        return None
    try:
        lines = (_I12_RUNTIME_ROOT / "pyvenv.cfg").read_text(encoding="utf-8").splitlines()
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
                str(_I12_INTERPRETER.parent),
                str(_I12_BASE_PYTHON_ROOT),
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
    try:
        return FixedChildCommand(
            (str(_I12_INTERPRETER), "-c", _I12_CHILD_ENTRY_SOURCE),
            Path(__file__).resolve().parents[1],
            environment,
            job_handle_env_name=_I12_JOB_HANDLE_ENV,
        )
    except (OSError, TypeError, ValueError):
        return None


def _fixed_i12_artifact_preflight_command(
    worker_command: FixedChildCommand,
) -> Optional[FixedChildCommand]:
    """Build a metadata-only verifier Job before consuming the I12 latch."""

    if type(worker_command) is not FixedChildCommand:
        return None
    source_root = str(worker_command.cwd)
    code = (
        "import json, sys\n"
        f"sys.path.insert(0, {source_root!r})\n"
        "payload = {'credential_resolver_invoked': False, 'native_join_pending': False, "
        "'reason': 'artifact_rejected', 'sdk_imported': False, 'status': 'rejected'}\n"
        "try:\n"
        "    from backtrader_runtime.ctp_artifact_provenance import "
        "CTP_I12_TD_ONLY_READONLY_ARTIFACT_PINS, "
        "verify_ctp_i12_td_only_readonly_artifact_provenance_for_fronts\n"
        "    from backtrader_runtime.ctp_i12_td_only_readonly import "
        "I12_REUSED_I10_WHEEL_SHA256, I12_SDK_SOURCE_COMMIT\n"
        f"    expected_base = {_I12_EXPECTED_BASE_ARTIFACT!r}\n"
        f"    expected_ctp = {_I12_EXPECTED_CTP_ARTIFACT!r}\n"
        "    facts = lambda pin: (pin.distribution, pin.module, pin.version, "
        "pin.wheel_filename, pin.wheel_sha256, pin.record_sha256)\n"
        "    pins = CTP_I12_TD_ONLY_READONLY_ARTIFACT_PINS\n"
        f"    if I12_SDK_SOURCE_COMMIT != {I12_SDK_SOURCE_COMMIT!r}: raise RuntimeError()\n"
        f"    if I12_REUSED_I10_WHEEL_SHA256 != {I12_REUSED_I10_WHEEL_SHA256!r}: raise RuntimeError()\n"
        "    if set(pins) != {'bt_api_base', 'bt_api_ctp'}: raise RuntimeError()\n"
        "    if facts(pins['bt_api_base']) != expected_base: raise RuntimeError()\n"
        "    if facts(pins['bt_api_ctp']) != expected_ctp: raise RuntimeError()\n"
        "    blocked = ('backtrader_runtime.credential_resolver', "
        "'backtrader_runtime.ctp_preflight', 'backtrader_runtime.ctp_sdk_readonly')\n"
        "    if any(name in sys.modules for name in blocked): raise RuntimeError()\n"
        "    verify_ctp_i12_td_only_readonly_artifact_provenance_for_fronts("
        "td_front='tcp://192.0.2.1:10130', md_front='tcp://192.0.2.2:10131')\n"
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
    try:
        return FixedChildCommand(
            (str(_I12_INTERPRETER), "-I", "-B", "-c", code),
            worker_command.cwd,
            environment,
        )
    except (OSError, TypeError, ValueError):
        return None


def _parse_i12_artifact_preflight_receipt(raw: bytes) -> Optional[Mapping[str, object]]:
    return parse_single_json_receipt(raw, _I12_ARTIFACT_PREFLIGHT_SCHEMA)


class _I12ArtifactPreflightLatch:
    """Process-local latch for the metadata-only verifier; no disk marker."""

    def __init__(self) -> None:
        self._tripped = False

    def is_tripped(self) -> bool:
        return self._tripped

    def trip(self, _reason: str) -> bool:
        self._tripped = True
        return True


def _i12_artifact_preflight_succeeded(result: object) -> bool:
    if type(result) is not SupervisedResult:
        return False
    receipt = result.sdk_receipt
    evidence = result.process_evidence
    try:
        valid_receipt = (
            type(receipt) is dict
            and _parse_i12_artifact_preflight_receipt(
                (json.dumps(receipt, sort_keys=True, separators=(",", ":")) + "\n").encode(
                    "utf-8"
                )
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
        and evidence.process_exit_code == 0
        and evidence.job_termination_requested is False
        and evidence.job_termination_call_succeeded is None
        and evidence.job_empty_observed is True
        and evidence.containment == "verified"
        and result.retained_control is None
    )


def _is_current_process_in_job() -> bool:
    if os.name != "nt":
        return False
    raw_handle = os.environ.pop(_I12_JOB_HANDLE_ENV, None)
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


def _has_supervised_i12_attempt_context() -> bool:
    if not _is_current_process_in_job():
        return False
    try:
        from .ctp_i12_td_only_latch import I12_LATCH_PATH, PersistentI12TdOnlyAttemptLatch

        return PersistentI12TdOnlyAttemptLatch(I12_LATCH_PATH).is_tripped() is True
    except Exception:
        return False


def _run_child_entry() -> int:
    return _run_diagnostic_impl()


def _empty_evidence(containment: str) -> ProcessEvidence:
    return ProcessEvidence(False, False, False, None, None, False, None, None, containment)


def _exact_receipt(value: object) -> Optional[Mapping[str, object]]:
    return _receipt_fields_complete(value)


def _parent_confirms_i12_readonly(result: object) -> bool:
    if type(result) is not SupervisedResult:
        return False
    receipt = _exact_receipt(result.sdk_receipt)
    evidence = result.process_evidence
    if receipt is None or type(evidence) is not ProcessEvidence:
        return False
    expected_queries = tuple(_QUERY_FIELD_NAMES.values())
    if (
        receipt["status"] != "td_readonly_complete"
        or receipt["reason"] != "td_readonly_query_bundle_closed"
        or receipt["stage"] != "td_session"
        or receipt["login_state"] != "verified"
        or receipt["query_bundle_complete"] is not True
        or receipt["query_values_redacted"] is not True
        or receipt["write_counts_state"] != "zero"
        or receipt["margin_rate_exchange_scope"] not in {"exact", "unverified"}
        or receipt["commission_rate_exchange_scope"] not in {"exact", "unverified"}
        or receipt["close_state"] != "complete"
        or receipt["native_join_pending"] is not False
        or receipt["native_release_complete"] is not True
        or receipt["join_required"] not in (True, False)
        or (
            receipt["join_required"] is True
            and receipt["join_completed"] is not True
        )
        or receipt["client_stop_returned"] is not True
        or any(receipt[name] != "complete" for name in expected_queries)
        or any(
            receipt[name] is not False
            for name in (
                "account_ready",
                "order_submission_authorized",
                "settlement_confirmation_called",
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
        and evidence.process_exit_code == 0
        and evidence.job_termination_requested is False
        and evidence.job_termination_call_succeeded is None
        and evidence.job_empty_observed is True
        and evidence.containment == "verified"
        and result.retained_control is None
    )


def _i12_deadline_expired(deadline_monotonic: float) -> bool:
    """Fail closed when the shared parent operation deadline is observed."""

    try:
        return time.monotonic() >= deadline_monotonic
    except Exception:
        return True


def _i12_deadline_error(error: BaseException, deadline_monotonic: float) -> bool:
    return _i12_deadline_expired(deadline_monotonic) or (
        isinstance(error, CtpFrontPairProbeError)
        and error.reason == "probe_global_deadline_exceeded"
    )


def _i12_timed_out_result(
    *, evidence: Optional[ProcessEvidence] = None, retained_control: Optional[object] = None
) -> SupervisedResult:
    return SupervisedResult(
        "timed_out",
        "child_deadline_exceeded",
        None,
        evidence if type(evidence) is ProcessEvidence else _empty_evidence("not_started"),
        retained_control,
    )


def _supervise_i12_child(
    fail_closed_latch: Optional[FailClosedLatch],
    *,
    precheck: Optional[Callable[[], I12FrontPrecheckBinding]] = None,
    command_builder: Optional[Callable[[I12FrontPrecheckBinding], Optional[FixedChildCommand]]] = None,
    artifact_command_builder: Optional[
        Callable[[FixedChildCommand], Optional[FixedChildCommand]]
    ] = None,
    runner: Optional[Callable[..., SupervisedResult]] = None,
) -> SupervisedResult:
    """Precheck without credentials, reserve I12 once, then supervise child.

    The shared monotonic deadline is observed around synchronous sealing,
    command construction, and latch calls, then passed to both contained Jobs.
    It cannot preempt a blocking Python callback, Windows process/Job API call,
    or cleanup routine that does not return control to the supervisor.
    """

    # One absolute deadline covers sealing, front selection, both contained
    # Jobs, and the one-shot latch transition.
    deadline_monotonic = time.monotonic() + _I12_TOTAL_DEADLINE_SECONDS
    if fail_closed_latch is None:
        return SupervisedResult(
            "supervisor_error",
            "i12_runtime_or_latch_unavailable",
            None,
            _empty_evidence("unavailable"),
        )
    if _i12_deadline_expired(deadline_monotonic):
        return _i12_timed_out_result()
    is_tripped = getattr(fail_closed_latch, "is_tripped", None)
    begin_attempt = getattr(fail_closed_latch, "begin_attempt", None)
    if not callable(is_tripped) or not callable(begin_attempt):
        return SupervisedResult(
            "supervisor_error",
            "i12_runtime_or_latch_unavailable",
            None,
            _empty_evidence("unavailable"),
        )
    try:
        binding = (
            _parent_credential_free_precheck(deadline_monotonic=deadline_monotonic)
            if precheck is None
            else precheck()
        )
    except Exception as error:
        if _i12_deadline_error(error, deadline_monotonic):
            return _i12_timed_out_result()
        return SupervisedResult(
            "rejected",
            "front_precheck_rejected",
            None,
            _empty_evidence("not_started"),
        )
    if _i12_deadline_expired(deadline_monotonic):
        return _i12_timed_out_result()
    if type(binding) is not I12FrontPrecheckBinding:
        return SupervisedResult(
            "rejected",
            "front_precheck_rejected",
            None,
            _empty_evidence("not_started"),
        )
    try:
        command = (command_builder or _fixed_i12_child_command)(binding)
    except Exception:
        if _i12_deadline_expired(deadline_monotonic):
            return _i12_timed_out_result()
        return SupervisedResult(
            "supervisor_error",
            "i12_runtime_or_latch_unavailable",
            None,
            _empty_evidence("unavailable"),
        )
    if _i12_deadline_expired(deadline_monotonic):
        return _i12_timed_out_result()
    if command is None:
        return SupervisedResult(
            "supervisor_error",
            "i12_runtime_or_latch_unavailable",
            None,
            _empty_evidence("unavailable"),
        )
    try:
        artifact_command = (artifact_command_builder or _fixed_i12_artifact_preflight_command)(
            command
        )
        if _i12_deadline_expired(deadline_monotonic):
            return _i12_timed_out_result()
        if artifact_command is None:
            return SupervisedResult(
                "supervisor_error",
                "i12_runtime_or_latch_unavailable",
                None,
                _empty_evidence("unavailable"),
            )
        active_runner = runner or run_readonly_child
        artifact_result = active_runner(
            artifact_command,
            _parse_i12_artifact_preflight_receipt,
            receipt_schema=_I12_ARTIFACT_PREFLIGHT_SCHEMA,
            fail_closed_latch=_I12ArtifactPreflightLatch(),
            deadline_seconds=10.0,
            deadline_monotonic=deadline_monotonic,
            max_stdout_bytes=4096,
            termination_grace_seconds=2.0,
        )
    except Exception:
        if _i12_deadline_expired(deadline_monotonic):
            return _i12_timed_out_result()
        return SupervisedResult(
            "supervisor_error",
            "i12_supervisor_failed",
            None,
            _empty_evidence("unavailable"),
        )
    global _I12_RETAINED_JOB_CONTROL
    if type(artifact_result) is SupervisedResult and artifact_result.retained_control is not None:
        _I12_RETAINED_JOB_CONTROL = artifact_result.retained_control
    if _i12_deadline_expired(deadline_monotonic):
        return _i12_timed_out_result(
            evidence=(
                artifact_result.process_evidence
                if type(artifact_result) is SupervisedResult
                else None
            ),
            retained_control=(
                artifact_result.retained_control
                if type(artifact_result) is SupervisedResult
                else None
            ),
        )
    if not _i12_artifact_preflight_succeeded(artifact_result):
        artifact_receipt = (
            artifact_result.sdk_receipt
            if type(artifact_result) is SupervisedResult
            else None
        )
        artifact_rejected = False
        if type(artifact_receipt) is dict:
            try:
                parsed_artifact = _parse_i12_artifact_preflight_receipt(
                    (
                        json.dumps(artifact_receipt, sort_keys=True, separators=(",", ":"))
                        + "\n"
                    ).encode("utf-8")
                )
                artifact_rejected = (
                    parsed_artifact == artifact_receipt
                    and artifact_receipt["status"] == "rejected"
                    and artifact_receipt["reason"] == "artifact_rejected"
                    and type(artifact_result) is SupervisedResult
                    and artifact_result.status == "child_exited"
                    and artifact_result.process_evidence.containment == "verified"
                )
            except (TypeError, ValueError, UnicodeError, AttributeError):
                artifact_rejected = False
        if artifact_rejected:
            return SupervisedResult(
                "rejected",
                "sdk_artifact_rejected",
                None,
                artifact_result.process_evidence,
                artifact_result.retained_control,
            )
        evidence = (
            artifact_result.process_evidence
            if type(artifact_result) is SupervisedResult
            and type(artifact_result.process_evidence) is ProcessEvidence
            else _empty_evidence("unavailable")
        )
        return SupervisedResult(
            "supervisor_error",
            "i12_supervisor_failed",
            None,
            evidence,
            artifact_result.retained_control
            if type(artifact_result) is SupervisedResult
            else None,
        )
    try:
        if _i12_deadline_expired(deadline_monotonic):
            return _i12_timed_out_result(evidence=artifact_result.process_evidence)
        already_tripped = is_tripped()
        if _i12_deadline_expired(deadline_monotonic):
            return _i12_timed_out_result(evidence=artifact_result.process_evidence)
        if already_tripped is True:
            return SupervisedResult(
                "latched",
                "prior_attempt_or_poisoned_latch",
                None,
                _empty_evidence("latched"),
            )
        if _i12_deadline_expired(deadline_monotonic):
            return _i12_timed_out_result(evidence=artifact_result.process_evidence)
        attempt_started = begin_attempt()
        if _i12_deadline_expired(deadline_monotonic):
            return _i12_timed_out_result(evidence=artifact_result.process_evidence)
        if attempt_started is not True:
            return SupervisedResult(
                "latched",
                "prior_attempt_or_poisoned_latch",
                None,
                _empty_evidence("latched"),
            )
        result = active_runner(
            command,
            parse_i12_child_receipt,
            receipt_schema=I12_CHILD_RECEIPT_SCHEMA,
            fail_closed_latch=fail_closed_latch,
            deadline_seconds=_I12_TOTAL_DEADLINE_SECONDS,
            deadline_monotonic=deadline_monotonic,
            max_stdout_bytes=_I12_MAX_STDOUT_BYTES,
            termination_grace_seconds=_I12_TERMINATION_GRACE_SECONDS,
        )
    except Exception:
        if _i12_deadline_expired(deadline_monotonic):
            return _i12_timed_out_result(evidence=artifact_result.process_evidence)
        return SupervisedResult(
            "supervisor_error",
            "i12_supervisor_failed",
            None,
            _empty_evidence("unavailable"),
        )
    if type(result) is not SupervisedResult:
        return SupervisedResult(
            "supervisor_error",
            "i12_supervisor_failed",
            None,
            _empty_evidence("unavailable"),
        )
    if result.retained_control is not None:
        _I12_RETAINED_JOB_CONTROL = result.retained_control
    if _i12_deadline_expired(deadline_monotonic):
        return _i12_timed_out_result(
            evidence=result.process_evidence,
            retained_control=result.retained_control,
        )
    if _parent_confirms_i12_readonly(result):
        return SupervisedResult(
            "td_readonly_complete",
            "td_readonly_query_bundle_closed",
            _exact_receipt(result.sdk_receipt),
            result.process_evidence,
            result.retained_control,
        )
    receipt = _exact_receipt(result.sdk_receipt)
    if receipt is not None and receipt["native_join_pending"] is True:
        return SupervisedResult(
            "pending_native_join",
            "native_join_pending",
            receipt,
            result.process_evidence,
            result.retained_control,
        )
    if receipt is not None:
        status = "incomplete" if receipt["status"] == "incomplete" else "rejected"
        reason = (
            "child_diagnostic_incomplete"
            if status == "incomplete"
            else "child_diagnostic_rejected"
        )
        return SupervisedResult(status, reason, receipt, result.process_evidence, result.retained_control)
    return result


def supervise_i12_td_only_child() -> SupervisedResult:
    """Unregistered I12 operator candidate; it never dispatches through inventory."""

    from .ctp_i12_td_only_latch import I12_LATCH_PATH, PersistentI12TdOnlyAttemptLatch

    return _supervise_i12_child(PersistentI12TdOnlyAttemptLatch(I12_LATCH_PATH))


def _parent_payload(result: SupervisedResult) -> dict[str, object]:
    evidence = result.process_evidence
    receipt = _exact_receipt(result.sdk_receipt)
    return {
        "process_evidence": {
            "containment": evidence.containment
            if evidence.containment
            in {"latched", "not_started", "unavailable", "uncertain", "verified"}
            else "unavailable",
            "job_assignment_observed": evidence.job_assignment_observed is True,
            "job_empty_observed": evidence.job_empty_observed
            if type(evidence.job_empty_observed) is bool
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
        },
        "reason": result.reason
        if result.reason in _I12_REASON_VALUES
        else "i12_supervisor_failed",
        "sdk_receipt": receipt,
        "status": result.status
        if result.status
        in {
            "child_exited",
            "incomplete",
            "latched",
            "pending_native_join",
            "rejected",
            "supervisor_error",
            "td_readonly_complete",
            "timed_out",
            "invalid_output",
        }
        else "supervisor_error",
    }


def main() -> int:
    """Fixed I12 one-shot entry for explicit supervised operator invocation."""

    if tuple(sys.argv[1:]):
        result = SupervisedResult(
            "rejected", "arguments_not_allowed", None, _empty_evidence("not_started")
        )
    else:
        result = supervise_i12_td_only_child()
    sys.stdout.write(json.dumps(_parent_payload(result), sort_keys=True) + "\n")
    sys.stdout.flush()
    if result.status == "td_readonly_complete":
        return 0
    if result.status in {"pending_native_join", "timed_out"}:
        return 3
    return 2


__all__ = [
    "I12_CHILD_RECEIPT_SCHEMA",
    "I12FrontPrecheckBinding",
    "I12TdOnlySessionEvidence",
    "main",
    "parse_i12_child_receipt",
    "supervise_i12_td_only_child",
]


if __name__ == "__main__":  # pragma: no cover - supervisor-only entry
    raise SystemExit(main())
