"""Pure value-free projection for a future I13 MD diagnostic trace.

This module has no SDK, credential, configuration, network, or latch imports.
It is an offline contract/fixture only; it is not wired to I10 or I11.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import AbstractSet, Dict, Optional, Sequence, Set


class I13PrimaryProbeReason(str, Enum):
    """Coarse probe outcomes. These describe observed events, not root cause."""

    MATCHING_TICK_OBSERVED = "matching_tick_observed"
    MARKET_FRONT_DISCONNECTED = "market_front_disconnected"
    MARKET_IDENTITY_UNVERIFIED = "market_identity_unverified"
    MARKET_LOGIN_TIMEOUT = "market_login_timeout"
    MARKET_OBSERVATION_INCOMPLETE = "market_observation_incomplete"
    MARKET_PROBE_FAILED = "market_probe_failed"
    MARKET_SUBSCRIPTION_REJECTED = "market_subscription_rejected"
    PROBE_DEADLINE_EXPIRED = "probe_deadline_expired"
    UNKNOWN = "unknown"


class I13ReasonSource(str, Enum):
    REPORTED_ADAPTER_REASON = "reported_adapter_reason"
    EVENT_TRACE = "event_trace"
    UNKNOWN = "unknown"


class I13EventKind(str, Enum):
    LOGIN_IDENTITY_UNVERIFIED = "login_identity_unverified"
    MARKET_FRONT_DISCONNECTED = "market_front_disconnected"
    MARKET_LOGIN_TIMEOUT = "market_login_timeout"
    OBSERVATION_WINDOW_CLOSED = "observation_window_closed"
    PROBE_DEADLINE_EXPIRED = "probe_deadline_expired"
    SUBSCRIPTION_ACKNOWLEDGED = "subscription_acknowledged"
    SUBSCRIPTION_REJECTED = "subscription_rejected"
    TICK_ARRIVED = "tick_arrived"
    TICK_SDK_REJECTED = "tick_sdk_rejected"
    TICK_ADAPTER_REJECTED = "tick_adapter_rejected"
    TICK_ACCEPTED = "tick_accepted"
    TICK_SAME_TRADING_DAY_CONFIRMED = "tick_same_trading_day_confirmed"
    NATIVE_JOIN_PENDING = "native_join_pending"
    NATIVE_JOIN_COMPLETED = "native_join_completed"


class I13TickRejectCode(str, Enum):
    ACK_MISSING = "ack_missing"
    BEFORE_ACK = "before_ack"
    EXCHANGE_MISMATCH = "exchange_mismatch"
    GENERATION_MISMATCH = "generation_mismatch"
    INSTRUMENT_MISMATCH = "instrument_mismatch"
    INVALID_LAST_PRICE = "invalid_last_price"
    INVALID_NATIVE_FIELDS = "invalid_native_fields"
    INVALID_VOLUME = "invalid_volume"
    TERMINAL_STATE = "terminal_state"
    TRADING_DAY_MISMATCH = "trading_day_mismatch"
    UNKNOWN = "unknown"


class I13TickClassification(str, Enum):
    ADAPTER_REJECTED = "adapter_rejected"
    EVIDENCE_INCONSISTENT = "evidence_inconsistent"
    NO_TICK_OBSERVED = "no_tick_observed"
    SDK_REJECTED = "sdk_rejected"
    TICK_ARRIVED_UNCLASSIFIED = "tick_arrived_unclassified"
    TICK_ACCEPTED = "tick_accepted"
    UNKNOWN = "unknown"


class I13AckTickOrder(str, Enum):
    ACK_BEFORE_ALL_TICKS = "ack_before_all_ticks"
    ACK_BETWEEN_TICKS = "ack_between_ticks"
    ACK_WITHOUT_TICK = "ack_without_tick"
    NEITHER_OBSERVED = "neither_observed"
    TICK_BEFORE_ACK = "tick_before_ack"
    TICK_WITHOUT_ACK = "tick_without_ack"
    UNKNOWN = "unknown"


class I13AcknowledgementState(str, Enum):
    ACKNOWLEDGED = "acknowledged"
    NOT_OBSERVED_AT_WINDOW_CLOSE = "not_observed_at_window_close"
    UNKNOWN = "unknown"


class I13NativeJoinState(str, Enum):
    COMPLETED_AFTER_PENDING = "completed_after_pending"
    COMPLETED = "completed"
    EVIDENCE_INCONSISTENT = "evidence_inconsistent"
    PENDING_OBSERVED = "pending_observed"
    UNKNOWN = "unknown"


class I13EvidenceIntegrity(str, Enum):
    INVALID = "invalid"
    VALID = "valid"


@dataclass(frozen=True)
class I13SdkLoginCallback:
    """Fixed classifications copied from the SDK receipt's login callback."""

    callback_count: int
    disposition: str
    request_id_relation: str
    response_error_status: str
    broker_id_shape: str
    user_id_shape: str
    trading_day_shape: str
    native_broker_id_shape: str
    native_user_id_shape: str

    def as_public_dict(self) -> Dict[str, object]:
        return {
            "broker_id_shape": self.broker_id_shape,
            "callback_count": self.callback_count,
            "disposition": self.disposition,
            "native_broker_id_shape": self.native_broker_id_shape,
            "native_user_id_shape": self.native_user_id_shape,
            "request_id_relation": self.request_id_relation,
            "response_error_status": self.response_error_status,
            "trading_day_shape": self.trading_day_shape,
            "user_id_shape": self.user_id_shape,
        }


@dataclass(frozen=True)
class I13SdkMdReceipt:
    """Strict value-free projection of the SDK's one-shot MD receipt."""

    receipt_observed: bool
    evidence_integrity: I13EvidenceIntegrity
    login_callback: Optional[I13SdkLoginCallback]
    terminal: Optional[bool]
    terminal_reason: Optional[str]
    subscription_submitted: Optional[bool]
    subscription_response_error_status: Optional[str]
    subscription_acknowledged: Optional[bool]
    first_tick_pending: Optional[bool]
    first_tick_received: Optional[bool]

    def as_public_dict(self) -> Dict[str, object]:
        return {
            "evidence_integrity": self.evidence_integrity.value,
            "first_tick_pending": self.first_tick_pending,
            "first_tick_received": self.first_tick_received,
            "login_callback": (
                None if self.login_callback is None else self.login_callback.as_public_dict()
            ),
            "receipt_observed": self.receipt_observed,
            "subscription_acknowledged": self.subscription_acknowledged,
            "subscription_response_error_status": self.subscription_response_error_status,
            "subscription_submitted": self.subscription_submitted,
            "terminal": self.terminal,
            "terminal_reason": self.terminal_reason,
        }


@dataclass(frozen=True)
class I13MdDiagnosticMerge:
    """Keep SDK receipt facts and downstream adapter facts in separate views."""

    sdk_receipt: I13SdkMdReceipt
    adapter_observability: I13MdObservability
    evidence_integrity: I13EvidenceIntegrity

    def as_public_dict(self) -> Dict[str, object]:
        return {
            "adapter_observability": self.adapter_observability.as_public_dict(),
            "evidence_integrity": self.evidence_integrity.value,
            "sdk_receipt": self.sdk_receipt.as_public_dict(),
        }


@dataclass(frozen=True)
class I13MdEvent:
    """One already-redacted event; ``tick_ordinal`` is local and non-identifying."""

    kind: I13EventKind
    tick_ordinal: Optional[int] = None
    rejection_code: Optional[I13TickRejectCode] = None
    elapsed_ms: Optional[int] = None


@dataclass(frozen=True)
class I13MdObservability:
    """Strict, value-free summary of the supplied event trace."""

    primary_probe_reason: I13PrimaryProbeReason
    primary_reason_source: I13ReasonSource
    tick_classification: I13TickClassification
    ack_tick_order: I13AckTickOrder
    acknowledgement_state: I13AcknowledgementState
    native_join_state: I13NativeJoinState
    evidence_integrity: I13EvidenceIntegrity
    tick_arrival_count: Optional[int]
    sdk_rejected_tick_count: Optional[int]
    adapter_rejected_tick_count: Optional[int]
    accepted_tick_count: Optional[int]
    same_trading_day_observed: Optional[bool]

    def as_public_dict(self) -> Dict[str, object]:
        """Return only fixed enum values, counts, and confirmed tri-state facts."""

        return {
            "accepted_tick_count": self.accepted_tick_count,
            "ack_tick_order": self.ack_tick_order.value,
            "acknowledgement_state": self.acknowledgement_state.value,
            "adapter_rejected_tick_count": self.adapter_rejected_tick_count,
            "evidence_integrity": self.evidence_integrity.value,
            "native_join_state": self.native_join_state.value,
            "primary_probe_reason": self.primary_probe_reason.value,
            "primary_reason_source": self.primary_reason_source.value,
            "same_trading_day_observed": self.same_trading_day_observed,
            "sdk_rejected_tick_count": self.sdk_rejected_tick_count,
            "tick_arrival_count": self.tick_arrival_count,
            "tick_classification": self.tick_classification.value,
        }


_REPORTED_PRIMARY_REASONS = {
    reason.value: reason
    for reason in (
        I13PrimaryProbeReason.MATCHING_TICK_OBSERVED,
        I13PrimaryProbeReason.MARKET_FRONT_DISCONNECTED,
        I13PrimaryProbeReason.MARKET_IDENTITY_UNVERIFIED,
        I13PrimaryProbeReason.MARKET_LOGIN_TIMEOUT,
        I13PrimaryProbeReason.MARKET_OBSERVATION_INCOMPLETE,
        I13PrimaryProbeReason.MARKET_PROBE_FAILED,
        I13PrimaryProbeReason.MARKET_SUBSCRIPTION_REJECTED,
        I13PrimaryProbeReason.PROBE_DEADLINE_EXPIRED,
    )
}

_TICK_EVENT_KINDS = frozenset(
    {
        I13EventKind.TICK_ARRIVED,
        I13EventKind.TICK_SDK_REJECTED,
        I13EventKind.TICK_ADAPTER_REJECTED,
        I13EventKind.TICK_ACCEPTED,
        I13EventKind.TICK_SAME_TRADING_DAY_CONFIRMED,
    }
)
_REJECTION_EVENT_KINDS = frozenset(
    {I13EventKind.TICK_SDK_REJECTED, I13EventKind.TICK_ADAPTER_REJECTED}
)
_PRIMARY_EVENT_REASONS = {
    I13EventKind.MARKET_FRONT_DISCONNECTED: I13PrimaryProbeReason.MARKET_FRONT_DISCONNECTED,
    I13EventKind.MARKET_LOGIN_TIMEOUT: I13PrimaryProbeReason.MARKET_LOGIN_TIMEOUT,
    I13EventKind.PROBE_DEADLINE_EXPIRED: I13PrimaryProbeReason.PROBE_DEADLINE_EXPIRED,
    I13EventKind.SUBSCRIPTION_REJECTED: I13PrimaryProbeReason.MARKET_SUBSCRIPTION_REJECTED,
}
_MAX_EVENTS = 256

_SDK_RECEIPT_FIELDS = frozenset(
    {
        "first_tick_pending",
        "first_tick_received",
        "login_callback",
        "subscription_acknowledged",
        "subscription_response_error_status",
        "subscription_submitted",
        "terminal",
        "terminal_reason",
    }
)
_SDK_LOGIN_CALLBACK_FIELDS = frozenset(
    {
        "broker_id_shape",
        "callback_count",
        "disposition",
        "native_broker_id_shape",
        "native_user_id_shape",
        "request_id_relation",
        "response_error_status",
        "trading_day_shape",
        "user_id_shape",
    }
)
_SDK_LOGIN_DISPOSITIONS = frozenset(
    {
        "accepted",
        "generation_mismatch",
        "identity_rejected",
        "identity_unverified",
        "none",
        "nonterminal",
        "provider_rejected",
        "request_id_mismatch",
        "request_id_type_invalid",
        "stale_spi",
        "terminal",
    }
)
_SDK_REQUEST_ID_RELATIONS = frozenset(
    {"not_observed", "invalid", "zero", "lower", "equal", "higher"}
)
_SDK_RESPONSE_ERROR_STATUSES = frozenset({"not_observed", "missing", "invalid", "zero", "nonzero"})
_SDK_BROKER_USER_SHAPES = frozenset(
    {
        "not_observed",
        "unreadable",
        "empty",
        "ascii_mismatch",
        "nonascii_or_replacement",
        "whitespace_or_control",
        "exact_match",
    }
)
_SDK_TRADING_DAY_SHAPES = frozenset(
    {
        "not_observed",
        "unreadable",
        "empty",
        "invalid_format",
        "invalid_calendar",
        "valid",
    }
)
_SDK_NATIVE_FIELD_SHAPES = frozenset(
    {"not_observed", "unreadable", "empty", "nonempty_terminated", "unterminated"}
)
_SDK_TERMINAL_REASONS = frozenset(
    {
        "broker_id_mismatch",
        "callback_failed:on_disconnect",
        "callback_failed:on_error",
        "callback_failed:on_identity_unverified",
        "callback_failed:on_login",
        "callback_failed:on_subscribe",
        "callback_failed:on_tick",
        "client_stopped",
        "diagnostic_complete",
        "duplicate_front_connected",
        "duplicate_login_callback",
        "duplicate_subscription_request",
        "front_disconnected",
        "identity_unverified_instrument_not_configured",
        "login_api_missing",
        "login_identity_rejected",
        "login_request_exception",
        "login_request_id_mismatch",
        "login_request_id_type_invalid",
        "login_request_rejected",
        "login_response_invalid",
        "login_response_nonterminal",
        "provider_login_rejected",
        "spi_callback_failed",
        "startup_failed",
        "subscription_connection_generation_mismatch",
        "subscription_instrument_mismatch",
        "subscription_rejected",
        "subscription_request_exception",
        "subscription_request_rejected",
        "subscription_response_invalid",
        "tick_before_subscription_ack",
        "tick_connection_generation_mismatch",
        "tick_instrument_mismatch",
        "tick_trading_day_mismatch",
        "trading_day_invalid",
        "trading_day_missing",
        "unexpected_login_callback",
        "unexpected_provider_error",
        "unexpected_subscription_callback",
        "user_id_mismatch",
    }
)


def _validate_events(events: object) -> Optional[tuple[I13MdEvent, ...]]:
    if type(events) not in (tuple, list) or len(events) > _MAX_EVENTS:
        return None
    validated = []
    last_elapsed = -1
    arrivals: Set[int] = set()
    outcomes: Set[int] = set()
    same_day_confirmations: Set[int] = set()
    for event in events:
        if type(event) is not I13MdEvent or type(event.kind) is not I13EventKind:
            return None
        if event.elapsed_ms is not None:
            if type(event.elapsed_ms) is not int or event.elapsed_ms < last_elapsed:
                return None
            last_elapsed = event.elapsed_ms
        if event.kind in _TICK_EVENT_KINDS:
            if type(event.tick_ordinal) is not int or event.tick_ordinal <= 0:
                return None
            if event.kind in _REJECTION_EVENT_KINDS:
                if type(event.rejection_code) is not I13TickRejectCode:
                    return None
            elif event.rejection_code is not None:
                return None
            if event.kind is I13EventKind.TICK_ARRIVED:
                if event.tick_ordinal in arrivals:
                    return None
                arrivals.add(event.tick_ordinal)
            elif event.kind in _REJECTION_EVENT_KINDS or event.kind is I13EventKind.TICK_ACCEPTED:
                if event.tick_ordinal in outcomes:
                    return None
                outcomes.add(event.tick_ordinal)
            elif event.kind is I13EventKind.TICK_SAME_TRADING_DAY_CONFIRMED:
                if event.tick_ordinal in same_day_confirmations:
                    return None
                same_day_confirmations.add(event.tick_ordinal)
        elif event.tick_ordinal is not None or event.rejection_code is not None:
            return None
        validated.append(event)

    for event in validated:
        if event.kind in _REJECTION_EVENT_KINDS or event.kind is I13EventKind.TICK_ACCEPTED:
            if event.tick_ordinal not in arrivals:
                return None
        if (
            event.kind is I13EventKind.TICK_SAME_TRADING_DAY_CONFIRMED
            and event.tick_ordinal not in arrivals
        ):
            return None

    sdk_rejected = {
        event.tick_ordinal for event in validated if event.kind is I13EventKind.TICK_SDK_REJECTED
    }
    adapter_day_mismatches = {
        event.tick_ordinal
        for event in validated
        if event.kind is I13EventKind.TICK_ADAPTER_REJECTED
        and event.rejection_code is I13TickRejectCode.TRADING_DAY_MISMATCH
    }
    if same_day_confirmations & (sdk_rejected | adapter_day_mismatches):
        return None
    return tuple(validated)


def _invalid_projection() -> I13MdObservability:
    return I13MdObservability(
        primary_probe_reason=I13PrimaryProbeReason.UNKNOWN,
        primary_reason_source=I13ReasonSource.UNKNOWN,
        tick_classification=I13TickClassification.EVIDENCE_INCONSISTENT,
        ack_tick_order=I13AckTickOrder.UNKNOWN,
        acknowledgement_state=I13AcknowledgementState.UNKNOWN,
        native_join_state=I13NativeJoinState.EVIDENCE_INCONSISTENT,
        evidence_integrity=I13EvidenceIntegrity.INVALID,
        tick_arrival_count=None,
        sdk_rejected_tick_count=None,
        adapter_rejected_tick_count=None,
        accepted_tick_count=None,
        same_trading_day_observed=None,
    )


def project_i13_md_observability(
    events: Sequence[object], *, reported_primary_reason: object = None
) -> I13MdObservability:
    """Project a bounded fake/future trace without copying arbitrary values.

    A reported reason is accepted only by exact enum string. In particular,
    ``native_join_pending`` is close evidence and deliberately is not treated as
    the primary market probe reason. When no reported reason is present, the
    trace can classify observed stages but cannot infer an underlying root cause.
    """

    trace = _validate_events(events)
    if trace is None:
        return _invalid_projection()

    reason = I13PrimaryProbeReason.UNKNOWN
    reason_source = I13ReasonSource.UNKNOWN
    if type(reported_primary_reason) is str:
        reason = _REPORTED_PRIMARY_REASONS.get(
            reported_primary_reason, I13PrimaryProbeReason.UNKNOWN
        )
        if reason is not I13PrimaryProbeReason.UNKNOWN:
            reason_source = I13ReasonSource.REPORTED_ADAPTER_REASON
    elif reported_primary_reason is None:
        for event in trace:
            event_reason = _PRIMARY_EVENT_REASONS.get(event.kind)
            if event_reason is not None:
                reason = event_reason
                reason_source = I13ReasonSource.EVENT_TRACE
                break
        else:
            if any(event.kind is I13EventKind.TICK_ACCEPTED for event in trace):
                reason = I13PrimaryProbeReason.MATCHING_TICK_OBSERVED
                reason_source = I13ReasonSource.EVENT_TRACE
            elif any(event.kind is I13EventKind.LOGIN_IDENTITY_UNVERIFIED for event in trace):
                reason = I13PrimaryProbeReason.MARKET_IDENTITY_UNVERIFIED
                reason_source = I13ReasonSource.EVENT_TRACE
            elif any(event.kind is I13EventKind.OBSERVATION_WINDOW_CLOSED for event in trace):
                reason = I13PrimaryProbeReason.MARKET_OBSERVATION_INCOMPLETE
                reason_source = I13ReasonSource.EVENT_TRACE

    arrival_indices = [
        index for index, event in enumerate(trace) if event.kind is I13EventKind.TICK_ARRIVED
    ]
    ack_indices = [
        index
        for index, event in enumerate(trace)
        if event.kind is I13EventKind.SUBSCRIPTION_ACKNOWLEDGED
    ]
    if len(ack_indices) > 1:
        return _invalid_projection()
    if ack_indices and arrival_indices:
        ack_index = ack_indices[0]
        if ack_index < min(arrival_indices):
            order = I13AckTickOrder.ACK_BEFORE_ALL_TICKS
        elif ack_index > max(arrival_indices):
            order = I13AckTickOrder.TICK_BEFORE_ACK
        else:
            order = I13AckTickOrder.ACK_BETWEEN_TICKS
    elif ack_indices:
        order = I13AckTickOrder.ACK_WITHOUT_TICK
    elif arrival_indices:
        order = I13AckTickOrder.TICK_WITHOUT_ACK
    else:
        order = I13AckTickOrder.NEITHER_OBSERVED

    ack_state = (
        I13AcknowledgementState.ACKNOWLEDGED
        if ack_indices
        else I13AcknowledgementState.NOT_OBSERVED_AT_WINDOW_CLOSE
        if any(event.kind is I13EventKind.OBSERVATION_WINDOW_CLOSED for event in trace)
        else I13AcknowledgementState.UNKNOWN
    )

    arrivals = {event.tick_ordinal for event in trace if event.kind is I13EventKind.TICK_ARRIVED}
    sdk_rejected = {
        event.tick_ordinal for event in trace if event.kind is I13EventKind.TICK_SDK_REJECTED
    }
    adapter_rejected = {
        event.tick_ordinal for event in trace if event.kind is I13EventKind.TICK_ADAPTER_REJECTED
    }
    accepted = {event.tick_ordinal for event in trace if event.kind is I13EventKind.TICK_ACCEPTED}
    if sdk_rejected & adapter_rejected or sdk_rejected & accepted or adapter_rejected & accepted:
        return _invalid_projection()
    if accepted:
        tick_classification = I13TickClassification.TICK_ACCEPTED
    elif adapter_rejected:
        tick_classification = I13TickClassification.ADAPTER_REJECTED
    elif sdk_rejected:
        tick_classification = I13TickClassification.SDK_REJECTED
    elif arrivals:
        tick_classification = I13TickClassification.TICK_ARRIVED_UNCLASSIFIED
    elif any(event.kind is I13EventKind.OBSERVATION_WINDOW_CLOSED for event in trace):
        tick_classification = I13TickClassification.NO_TICK_OBSERVED
    else:
        tick_classification = I13TickClassification.UNKNOWN

    join_events = [
        event.kind
        for event in trace
        if event.kind in {I13EventKind.NATIVE_JOIN_PENDING, I13EventKind.NATIVE_JOIN_COMPLETED}
    ]
    if I13EventKind.NATIVE_JOIN_COMPLETED in join_events:
        if join_events[-1] is I13EventKind.NATIVE_JOIN_PENDING:
            join_state = I13NativeJoinState.EVIDENCE_INCONSISTENT
        elif I13EventKind.NATIVE_JOIN_PENDING in join_events:
            join_state = I13NativeJoinState.COMPLETED_AFTER_PENDING
        else:
            join_state = I13NativeJoinState.COMPLETED
    elif I13EventKind.NATIVE_JOIN_PENDING in join_events:
        join_state = I13NativeJoinState.PENDING_OBSERVED
    else:
        join_state = I13NativeJoinState.UNKNOWN

    same_day_ordinals = {
        event.tick_ordinal
        for event in trace
        if event.kind is I13EventKind.TICK_SAME_TRADING_DAY_CONFIRMED
    }
    same_day_observed = True if same_day_ordinals else None

    return I13MdObservability(
        primary_probe_reason=reason,
        primary_reason_source=reason_source,
        tick_classification=tick_classification,
        ack_tick_order=order,
        acknowledgement_state=ack_state,
        native_join_state=join_state,
        evidence_integrity=I13EvidenceIntegrity.VALID,
        tick_arrival_count=len(arrivals),
        sdk_rejected_tick_count=len(sdk_rejected),
        adapter_rejected_tick_count=len(adapter_rejected),
        accepted_tick_count=len(accepted),
        same_trading_day_observed=same_day_observed,
    )


def _record_fields(value: object, name: str, expected: AbstractSet[str]) -> Optional[dict]:
    """Read an exact dataclass-shaped record without reflecting its values."""

    if type(value).__name__ != name:
        return None
    try:
        instance_fields = vars(value)
        declared_fields = type(value).__dataclass_fields__
    except Exception:
        return None
    if type(instance_fields) is not dict or type(declared_fields) is not dict:
        return None
    if set(instance_fields) != expected or set(declared_fields) != expected:
        return None
    return instance_fields


def _fixed_enum_code(value: object, allowed: AbstractSet[str]) -> Optional[str]:
    if not isinstance(value, Enum):
        return None
    try:
        code = value.value
    except Exception:
        return None
    return code if type(code) is str and code in allowed else None


def _unknown_sdk_receipt(*, observed: bool, integrity: I13EvidenceIntegrity) -> I13SdkMdReceipt:
    return I13SdkMdReceipt(
        receipt_observed=observed,
        evidence_integrity=integrity,
        login_callback=None,
        terminal=None,
        terminal_reason=None,
        subscription_submitted=None,
        subscription_response_error_status=None,
        subscription_acknowledged=None,
        first_tick_pending=None,
        first_tick_received=None,
    )


def project_i13_sdk_md_receipt(receipt: object) -> I13SdkMdReceipt:
    """Copy only fixed classifications from an SDK receipt-shaped dataclass.

    This intentionally imports no SDK modules. ``None`` means no receipt was
    supplied and remains unknown; malformed records, arbitrary enum values,
    and added fields fail closed without exposing their contents.
    """

    if receipt is None:
        return _unknown_sdk_receipt(observed=False, integrity=I13EvidenceIntegrity.VALID)

    values = _record_fields(receipt, "MdOneShotDiagnosticReceipt", _SDK_RECEIPT_FIELDS)
    if values is None:
        return _unknown_sdk_receipt(observed=True, integrity=I13EvidenceIntegrity.INVALID)

    callback_values = _record_fields(
        values["login_callback"], "MdLoginCallbackDiagnostic", _SDK_LOGIN_CALLBACK_FIELDS
    )
    if callback_values is None:
        return _unknown_sdk_receipt(observed=True, integrity=I13EvidenceIntegrity.INVALID)

    callback_count = callback_values["callback_count"]
    disposition = _fixed_enum_code(callback_values["disposition"], _SDK_LOGIN_DISPOSITIONS)
    request_id_relation = _fixed_enum_code(
        callback_values["request_id_relation"], _SDK_REQUEST_ID_RELATIONS
    )
    response_error_status = _fixed_enum_code(
        callback_values["response_error_status"], _SDK_RESPONSE_ERROR_STATUSES
    )
    broker_id_shape = _fixed_enum_code(callback_values["broker_id_shape"], _SDK_BROKER_USER_SHAPES)
    user_id_shape = _fixed_enum_code(callback_values["user_id_shape"], _SDK_BROKER_USER_SHAPES)
    trading_day_shape = _fixed_enum_code(
        callback_values["trading_day_shape"], _SDK_TRADING_DAY_SHAPES
    )
    native_broker_id_shape = _fixed_enum_code(
        callback_values["native_broker_id_shape"], _SDK_NATIVE_FIELD_SHAPES
    )
    native_user_id_shape = _fixed_enum_code(
        callback_values["native_user_id_shape"], _SDK_NATIVE_FIELD_SHAPES
    )

    terminal = values["terminal"]
    terminal_reason = values["terminal_reason"]
    subscription_submitted = values["subscription_submitted"]
    subscription_status = _fixed_enum_code(
        values["subscription_response_error_status"], _SDK_RESPONSE_ERROR_STATUSES
    )
    subscription_acknowledged = values["subscription_acknowledged"]
    first_tick_pending = values["first_tick_pending"]
    first_tick_received = values["first_tick_received"]

    callback_codes = (
        disposition,
        request_id_relation,
        response_error_status,
        broker_id_shape,
        user_id_shape,
        trading_day_shape,
        native_broker_id_shape,
        native_user_id_shape,
    )
    if (
        type(callback_count) is not int
        or not 0 <= callback_count <= _MAX_EVENTS
        or any(code is None for code in callback_codes)
        or type(terminal) is not bool
        or type(subscription_submitted) is not bool
        or type(subscription_acknowledged) is not bool
        or type(first_tick_pending) is not bool
        or type(first_tick_received) is not bool
        or subscription_status is None
        or (
            terminal_reason is not None
            and (type(terminal_reason) is not str or terminal_reason not in _SDK_TERMINAL_REASONS)
        )
    ):
        return _unknown_sdk_receipt(observed=True, integrity=I13EvidenceIntegrity.INVALID)

    callback_derived_codes = (
        request_id_relation,
        response_error_status,
        broker_id_shape,
        user_id_shape,
        trading_day_shape,
        native_broker_id_shape,
        native_user_id_shape,
    )
    if (
        (terminal != (terminal_reason is not None))
        or (callback_count == 0 and disposition != "none")
        or (callback_count == 0 and any(code != "not_observed" for code in callback_derived_codes))
        or (callback_count > 0 and disposition == "none")
        or (subscription_acknowledged and not subscription_submitted)
        or (subscription_acknowledged and subscription_status != "zero")
        or (first_tick_pending and first_tick_received)
        or (first_tick_pending and not subscription_submitted)
        or (
            first_tick_received
            and not (subscription_submitted and subscription_acknowledged and terminal)
        )
    ):
        return _unknown_sdk_receipt(observed=True, integrity=I13EvidenceIntegrity.INVALID)

    login_callback = I13SdkLoginCallback(
        callback_count=callback_count,
        disposition=disposition,
        request_id_relation=request_id_relation,
        response_error_status=response_error_status,
        broker_id_shape=broker_id_shape,
        user_id_shape=user_id_shape,
        trading_day_shape=trading_day_shape,
        native_broker_id_shape=native_broker_id_shape,
        native_user_id_shape=native_user_id_shape,
    )
    return I13SdkMdReceipt(
        receipt_observed=True,
        evidence_integrity=I13EvidenceIntegrity.VALID,
        login_callback=login_callback,
        terminal=terminal,
        terminal_reason=terminal_reason,
        subscription_submitted=subscription_submitted,
        subscription_response_error_status=subscription_status,
        subscription_acknowledged=subscription_acknowledged,
        first_tick_pending=first_tick_pending,
        first_tick_received=first_tick_received,
    )


def merge_i13_md_diagnostic_receipt(
    receipt: object,
    adapter_events: Sequence[object],
    *,
    reported_primary_reason: object = None,
) -> I13MdDiagnosticMerge:
    """Project SDK receipt facts beside, but never into, adapter tick facts.

    Receipt ACK and first-tick flags retain their own provenance. In
    particular, SDK first-tick acceptance does not become downstream adapter
    acceptance or same-TradingDay evidence, and the two sources cannot invent
    an ACK/tick callback order. Native Join remains solely in the adapter
    lifecycle event projection.
    """

    sdk = project_i13_sdk_md_receipt(receipt)
    adapter = project_i13_md_observability(
        adapter_events, reported_primary_reason=reported_primary_reason
    )
    integrity = (
        I13EvidenceIntegrity.VALID
        if sdk.evidence_integrity is I13EvidenceIntegrity.VALID
        and adapter.evidence_integrity is I13EvidenceIntegrity.VALID
        else I13EvidenceIntegrity.INVALID
    )
    trace = _validate_events(adapter_events)
    if trace is None:
        integrity = I13EvidenceIntegrity.INVALID
    elif sdk.evidence_integrity is I13EvidenceIntegrity.VALID and sdk.receipt_observed:
        has_adapter_ack = any(
            event.kind is I13EventKind.SUBSCRIPTION_ACKNOWLEDGED for event in trace
        )
        has_adapter_tick = any(event.kind is I13EventKind.TICK_ARRIVED for event in trace)
        has_subscription_rejection = any(
            event.kind is I13EventKind.SUBSCRIPTION_REJECTED for event in trace
        )
        if (
            (sdk.subscription_acknowledged is False and has_adapter_ack)
            or (sdk.subscription_acknowledged is True and has_subscription_rejection)
            or (
                has_adapter_tick
                and (sdk.first_tick_received is False or sdk.first_tick_pending is True)
            )
        ):
            integrity = I13EvidenceIntegrity.INVALID

    return I13MdDiagnosticMerge(
        sdk_receipt=sdk,
        adapter_observability=adapter,
        evidence_integrity=integrity,
    )
