"""Non-authorizing contracts for a proposed bounded SimNow G6-S window.

These DTOs are deliberately separate from :mod:`ctp_f14_external_admission`.
They bind a proposed one-action approval and a single native query stream to a
SimNow simulation scope.  They do not establish an account-wide writer fence,
a common account snapshot, a cryptographic signature, or write authority.
There is no production/CLI/Store/SDK integration or default verifier here.

An injected reviewer/verifier protocol is useful for fake-only contract tests.
Its return values are not trusted evidence until a future code-owned,
independently reviewed integration authenticates the review source and holds
the required local lease at its actual call sites.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Optional, Protocol, Tuple


_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
_ACTION_TTL_SECONDS = 60.0
_QUERY_KINDS = frozenset(
    ("account_funds", "open_orders", "positions", "trades", "settlement_confirmation")
)
_SCOPE_DOMAIN = b"backtrader-ctp-simnow-operational-window-scope-v1\0"
_ACTION_DOMAIN = b"backtrader-ctp-simnow-operational-window-action-v1\0"
_QUERY_DOMAIN = b"backtrader-ctp-simnow-single-query-v1\0"


class CtpSimNowOperationalWindowError(ValueError):
    """Redacted failure from this non-authorizing contract seam."""

    def __init__(self, reason: str) -> None:
        self.reason = reason
        super().__init__(reason.replace("_", " "))


def _reject(reason: str) -> None:
    raise CtpSimNowOperationalWindowError(reason) from None


def _require_id(value: object, field_name: str) -> str:
    if type(value) is not str or _ID_RE.fullmatch(value) is None:
        _reject("invalid_" + field_name)
    return value


def _require_digest(value: object, field_name: str) -> str:
    if type(value) is not str or _SHA256_RE.fullmatch(value) is None:
        _reject("invalid_" + field_name)
    return value


def _timestamp(value: object, field_name: str) -> float:
    if type(value) not in (int, float) or not math.isfinite(float(value)):
        _reject("invalid_" + field_name)
    return float(value)


def _canonical_digest(value: object, domain: bytes) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(domain + encoded.encode("ascii")).hexdigest()


def _decimal_text(value: Decimal) -> str:
    return format(value, "f")


@dataclass(frozen=True, repr=False)
class CtpSimNowOperationalRiskLimits:
    """Risk ceiling for the single bounded operational test order."""

    max_order_quantity: int
    max_gross_position_quantity: int
    max_live_test_orders: int
    max_order_notional: Decimal = field(repr=False)

    def __post_init__(self) -> None:
        if (
            type(self.max_order_quantity) is not int
            or self.max_order_quantity != 1
            or type(self.max_gross_position_quantity) is not int
            or self.max_gross_position_quantity != 1
            or type(self.max_live_test_orders) is not int
            or self.max_live_test_orders != 1
            or type(self.max_order_notional) is not Decimal
            or not self.max_order_notional.is_finite()
            or self.max_order_notional <= 0
        ):
            _reject("operational_risk_limits_invalid")

    @property
    def digest(self) -> str:
        return _canonical_digest(
            {
                "max_gross_position_quantity": self.max_gross_position_quantity,
                "max_live_test_orders": self.max_live_test_orders,
                "max_order_notional": _decimal_text(self.max_order_notional),
                "max_order_quantity": self.max_order_quantity,
            },
            _SCOPE_DOMAIN,
        )


@dataclass(frozen=True, repr=False)
class CtpSimNowOperationalWindowScope:
    """Exact simulation-only identity for one named operational test window."""

    window_id: str
    runtime_id: str
    environment: str
    mode: str
    preset: str
    account_fingerprint_sha256: str = field(repr=False)
    config_digest: str
    effective_digest: str
    registration_digest: str
    artifact_set_digest: str
    session_id: str
    trading_day: str
    connection_generation: int
    session_identity_digest: str
    selected_front_pair: Tuple[str, str] = field(repr=False)
    instrument_id: str
    exchange_id: str
    hedge_flag: str
    risk_limits: CtpSimNowOperationalRiskLimits = field(repr=False)

    def __post_init__(self) -> None:
        _require_id(self.window_id, "window_id")
        _require_id(self.runtime_id, "runtime_id")
        if (self.environment, self.mode, self.preset) != ("simnow", "simulation", "sandbox"):
            _reject("operational_window_must_be_simnow_sandbox")
        for name in (
            "account_fingerprint_sha256",
            "config_digest",
            "effective_digest",
            "registration_digest",
            "artifact_set_digest",
            "session_identity_digest",
        ):
            _require_digest(getattr(self, name), name)
        _require_id(self.session_id, "session_id")
        if type(self.trading_day) is not str or re.fullmatch(r"[0-9]{8}", self.trading_day) is None:
            _reject("invalid_trading_day")
        if type(self.connection_generation) is not int or self.connection_generation <= 0:
            _reject("invalid_connection_generation")
        if (
            type(self.selected_front_pair) is not tuple
            or len(self.selected_front_pair) != 2
            or any(
                type(front) is not str or not front or front != front.strip()
                for front in self.selected_front_pair
            )
            or self.selected_front_pair[0] == self.selected_front_pair[1]
        ):
            _reject("selected_front_pair_invalid")
        for name in ("instrument_id", "exchange_id"):
            value = getattr(self, name)
            if type(value) is not str or not value or value != value.strip():
                _reject("invalid_" + name)
        if self.hedge_flag not in ("1", "2", "3"):
            _reject("invalid_hedge_flag")
        if type(self.risk_limits) is not CtpSimNowOperationalRiskLimits:
            _reject("operational_risk_limits_required")

    @property
    def selected_front_pair_sha256(self) -> str:
        return _canonical_digest(self.selected_front_pair, _SCOPE_DOMAIN)

    @property
    def scope_digest(self) -> str:
        return _canonical_digest(
            {
                "account_fingerprint_sha256": self.account_fingerprint_sha256,
                "artifact_set_digest": self.artifact_set_digest,
                "config_digest": self.config_digest,
                "effective_digest": self.effective_digest,
                "environment": self.environment,
                "exchange_id": self.exchange_id,
                "hedge_flag": self.hedge_flag,
                "instrument_id": self.instrument_id,
                "mode": self.mode,
                "preset": self.preset,
                "registration_digest": self.registration_digest,
                "risk_limits_digest": self.risk_limits.digest,
                "runtime_id": self.runtime_id,
                "selected_front_pair": self.selected_front_pair,
                "session": {
                    "connection_generation": self.connection_generation,
                    "identity_digest": self.session_identity_digest,
                    "session_id": self.session_id,
                    "trading_day": self.trading_day,
                },
                "window_id": self.window_id,
            },
            _SCOPE_DOMAIN,
        )

    @property
    def account_writer_exclusive(self) -> bool:
        """Always false: local/operational scope is not a broker fence."""

        return False

    @property
    def common_snapshot_verified(self) -> bool:
        """Always false: this scope contains no cross-query snapshot claim."""

        return False


@dataclass(frozen=True, repr=False)
class CtpSimNowOperationalActionRequest:
    """One exact proposed test action bound to a named SimNow window."""

    scope: CtpSimNowOperationalWindowScope = field(repr=False)
    action_kind: str
    action_id: str
    action_digest: str
    approval_digest: str
    requested_quantity: Optional[int] = None
    requested_notional: Optional[Decimal] = field(default=None, repr=False)
    target_digest: Optional[str] = None
    target_remaining_quantity: Optional[int] = None

    def __post_init__(self) -> None:
        if type(self.scope) is not CtpSimNowOperationalWindowScope:
            _reject("operational_window_scope_required")
        if type(self.action_kind) is not str or self.action_kind not in ("SUBMIT", "CANCEL"):
            _reject("operational_action_kind_invalid")
        _require_id(self.action_id, "action_id")
        for name in ("action_digest", "approval_digest"):
            _require_digest(getattr(self, name), name)
        if self.action_kind == "SUBMIT":
            if (
                type(self.requested_quantity) is not int
                or self.requested_quantity <= 0
                or self.requested_quantity > self.scope.risk_limits.max_order_quantity
                or self.requested_quantity > self.scope.risk_limits.max_gross_position_quantity
                or type(self.requested_notional) is not Decimal
                or not self.requested_notional.is_finite()
                or self.requested_notional <= 0
                or self.requested_notional > self.scope.risk_limits.max_order_notional
                or self.target_digest is not None
                or self.target_remaining_quantity is not None
            ):
                _reject("operational_submit_exceeds_or_misses_risk_scope")
        elif (
            self.requested_quantity is not None
            or self.requested_notional is not None
            or self.target_digest is None
            or self.target_remaining_quantity is None
            or type(self.target_remaining_quantity) is not int
            or self.target_remaining_quantity <= 0
            or self.target_remaining_quantity > self.scope.risk_limits.max_order_quantity
        ):
            _reject("operational_cancel_target_invalid")
        else:
            _require_digest(self.target_digest, "target_digest")

    @property
    def request_digest(self) -> str:
        return _canonical_digest(
            {
                "action_digest": self.action_digest,
                "action_id": self.action_id,
                "action_kind": self.action_kind,
                "approval_digest": self.approval_digest,
                "requested_notional": (
                    _decimal_text(self.requested_notional)
                    if self.requested_notional is not None
                    else None
                ),
                "requested_quantity": self.requested_quantity,
                "scope_digest": self.scope.scope_digest,
                "target_digest": self.target_digest,
                "target_remaining_quantity": self.target_remaining_quantity,
            },
            _ACTION_DOMAIN,
        )


@dataclass(frozen=True, repr=False)
class CtpSimNowOperationalWindowPermit:
    """Non-authorizing, short-lived review record for exactly one action.

    ``review_digest`` is a reference digest only.  This type does not verify a
    signature or an operator identity.  Its fixed false properties prevent it
    from representing strict F14 writer exclusion or a common snapshot.
    """

    binding: CtpSimNowOperationalActionRequest = field(repr=False)
    permit_id: str
    review_authority_id: str
    review_digest: str
    revocation_epoch: int
    issued_at_utc: float
    expires_at_utc: float

    def __post_init__(self) -> None:
        if type(self.binding) is not CtpSimNowOperationalActionRequest:
            _reject("operational_permit_binding_invalid")
        for name in ("permit_id", "review_authority_id"):
            _require_id(getattr(self, name), name)
        _require_digest(self.review_digest, "review_digest")
        if type(self.revocation_epoch) is not int or self.revocation_epoch <= 0:
            _reject("operational_revocation_epoch_invalid")
        issued = _timestamp(self.issued_at_utc, "issued_at_utc")
        expires = _timestamp(self.expires_at_utc, "expires_at_utc")
        if expires <= issued or expires - issued > _ACTION_TTL_SECONDS:
            _reject("operational_permit_expiry_invalid")

    @property
    def scope_digest(self) -> str:
        return self.binding.scope.scope_digest

    @property
    def request_digest(self) -> str:
        return self.binding.request_digest

    @property
    def permit_digest(self) -> str:
        """Stable summary of validity/revocation fields; not a signature."""

        return _canonical_digest(
            {
                "binding_digest": self.binding.request_digest,
                "expires_at_utc": float(self.expires_at_utc),
                "issued_at_utc": float(self.issued_at_utc),
                "permit_id": self.permit_id,
                "revocation_epoch": self.revocation_epoch,
                "review_authority_id": self.review_authority_id,
                "review_digest": self.review_digest,
            },
            _ACTION_DOMAIN,
        )

    @property
    def account_writer_exclusive(self) -> bool:
        return False

    @property
    def common_snapshot_verified(self) -> bool:
        return False

    @property
    def cryptographic_signature_verified(self) -> bool:
        return False

    @property
    def write_authorized(self) -> bool:
        return False


class CtpSimNowOperationalWindowReviewer(Protocol):
    """Unimplemented review/revocation source; local fakes are non-authorizing."""

    def issue_action_review(
        self, request: CtpSimNowOperationalActionRequest
    ) -> CtpSimNowOperationalWindowPermit:
        """Return an independently reviewed, exact-scope record."""

        ...

    def assert_action_review_current(
        self,
        permit: CtpSimNowOperationalWindowPermit,
        *,
        request: CtpSimNowOperationalActionRequest,
    ) -> bool:
        """Return literal True only while the review is unrevoked and current."""

        ...


class CtpSimNowQueryKind:
    """Names for one request stream; these names imply no account coverage."""

    ACCOUNT_FUNDS = "account_funds"
    OPEN_ORDERS = "open_orders"
    POSITIONS = "positions"
    TRADES = "trades"
    SETTLEMENT_CONFIRMATION = "settlement_confirmation"


@dataclass(frozen=True, repr=False)
class CtpSimNowQueryRequest:
    """One native query request bound to a SimNow operational window."""

    scope: CtpSimNowOperationalWindowScope = field(repr=False)
    query_id: str
    query_kind: str
    request_id: int
    filters_digest: str

    def __post_init__(self) -> None:
        if type(self.scope) is not CtpSimNowOperationalWindowScope:
            _reject("query_window_scope_required")
        _require_id(self.query_id, "query_id")
        if type(self.query_kind) is not str or self.query_kind not in _QUERY_KINDS:
            _reject("query_kind_invalid")
        if type(self.request_id) is not int or self.request_id <= 0:
            _reject("query_request_id_invalid")
        _require_digest(self.filters_digest, "query_filters_digest")

    @property
    def request_digest(self) -> str:
        return _canonical_digest(
            {
                "filters_digest": self.filters_digest,
                "query_id": self.query_id,
                "query_kind": self.query_kind,
                "request_id": self.request_id,
                "scope_digest": self.scope.scope_digest,
            },
            _QUERY_DOMAIN,
        )


@dataclass(frozen=True, repr=False)
class CtpSimNowSingleQueryObservation:
    """Evidence facts for exactly one native request/response stream."""

    binding: CtpSimNowQueryRequest = field(repr=False)
    b_is_last: bool
    response_error_code: int
    callback_count: int
    late_callback_count: int
    record_count: int
    records_digest: str
    source_evidence_digest: str
    started_at_utc: float
    terminal_at_utc: float

    def __post_init__(self) -> None:
        if type(self.binding) is not CtpSimNowQueryRequest:
            _reject("single_query_binding_invalid")
        if type(self.b_is_last) is not bool:
            _reject("single_query_terminal_flag_invalid")
        if type(self.response_error_code) is not int:
            _reject("single_query_error_code_invalid")
        for name in ("callback_count", "late_callback_count", "record_count"):
            value = getattr(self, name)
            if type(value) is not int or value < 0:
                _reject("single_query_count_invalid")
        for name in ("records_digest", "source_evidence_digest"):
            _require_digest(getattr(self, name), name)
        started = _timestamp(self.started_at_utc, "query_started_at_utc")
        terminal = _timestamp(self.terminal_at_utc, "query_terminal_at_utc")
        if terminal < started:
            _reject("single_query_time_order_invalid")

    @property
    def request_digest(self) -> str:
        return self.binding.request_digest

    @property
    def account_writer_exclusive(self) -> bool:
        return False

    @property
    def common_snapshot_verified(self) -> bool:
        return False

    @property
    def account_coverage_verified(self) -> bool:
        return False


class CtpSimNowSingleQueryVerifier(Protocol):
    """Proposed native-source verifier; no implementation is supplied here."""

    def verify_single_query(
        self,
        observation: CtpSimNowSingleQueryObservation,
        *,
        expected_request: CtpSimNowQueryRequest,
    ) -> bool:
        """Verify source, exact request, session, filters and this stream's terminal callback."""

        ...


def require_simnow_operational_window_permit(
    reviewer: CtpSimNowOperationalWindowReviewer,
    request: CtpSimNowOperationalActionRequest,
    *,
    now_utc: float,
) -> CtpSimNowOperationalWindowPermit:
    """Fetch and validate a fake-testable review record; this grants no route."""

    if type(request) is not CtpSimNowOperationalActionRequest:
        _reject("operational_action_request_required")
    now = _timestamp(now_utc, "now_utc")
    issue = getattr(reviewer, "issue_action_review", None)
    check = getattr(reviewer, "assert_action_review_current", None)
    if not callable(issue) or not callable(check):
        _reject("operational_window_reviewer_required")
    try:
        permit = issue(request)
    except Exception:
        _reject("operational_window_review_unavailable")
    if type(permit) is not CtpSimNowOperationalWindowPermit or permit.binding != request:
        _reject("operational_window_review_scope_mismatch")
    if now < permit.issued_at_utc or now >= permit.expires_at_utc:
        _reject("operational_window_review_expired")
    try:
        active = check(permit, request=request)
    except Exception:
        _reject("operational_window_revocation_check_unavailable")
    if active is not True:
        _reject("operational_window_review_revoked")
    return permit


def require_active_simnow_operational_window_permit(
    reviewer: CtpSimNowOperationalWindowReviewer,
    permit: CtpSimNowOperationalWindowPermit,
    request: CtpSimNowOperationalActionRequest,
    *,
    now_utc: float,
) -> None:
    """Recheck exact binding, expiry and external revocation state."""

    if (
        type(permit) is not CtpSimNowOperationalWindowPermit
        or type(request) is not CtpSimNowOperationalActionRequest
        or permit.binding != request
    ):
        _reject("operational_window_review_scope_mismatch")
    now = _timestamp(now_utc, "now_utc")
    if now < permit.issued_at_utc or now >= permit.expires_at_utc:
        _reject("operational_window_review_expired")
    check = getattr(reviewer, "assert_action_review_current", None)
    if not callable(check):
        _reject("operational_window_reviewer_required")
    try:
        active = check(permit, request=request)
    except Exception:
        _reject("operational_window_revocation_check_unavailable")
    if active is not True:
        _reject("operational_window_review_revoked")


def require_simnow_single_query_observation(
    verifier: CtpSimNowSingleQueryVerifier,
    observation: CtpSimNowSingleQueryObservation,
    *,
    expected_request: CtpSimNowQueryRequest,
) -> None:
    """Accept one verified terminal stream only; never assemble a snapshot."""

    if (
        type(observation) is not CtpSimNowSingleQueryObservation
        or type(expected_request) is not CtpSimNowQueryRequest
        or observation.binding != expected_request
    ):
        _reject("single_query_scope_mismatch")
    if (
        observation.b_is_last is not True
        or observation.response_error_code != 0
        or observation.callback_count <= 0
        or observation.late_callback_count != 0
    ):
        _reject("single_query_terminal_evidence_incomplete")
    verify = getattr(verifier, "verify_single_query", None)
    if not callable(verify):
        _reject("single_query_verifier_required")
    try:
        verified = verify(observation, expected_request=expected_request)
    except Exception:
        _reject("single_query_source_verification_unavailable")
    if verified is not True:
        _reject("single_query_source_unverified")


__all__ = [
    "CtpSimNowOperationalActionRequest",
    "CtpSimNowOperationalRiskLimits",
    "CtpSimNowOperationalWindowError",
    "CtpSimNowOperationalWindowPermit",
    "CtpSimNowOperationalWindowReviewer",
    "CtpSimNowOperationalWindowScope",
    "CtpSimNowQueryKind",
    "CtpSimNowQueryRequest",
    "CtpSimNowSingleQueryObservation",
    "CtpSimNowSingleQueryVerifier",
    "require_active_simnow_operational_window_permit",
    "require_simnow_operational_window_permit",
    "require_simnow_single_query_observation",
]
