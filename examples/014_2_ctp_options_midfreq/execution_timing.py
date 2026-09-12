"""Immutable, local MF-T1 execution timing and risk projections.

This module deliberately stops at a read model.  It consumes an explicit
scope, clock observation, and execution-fact snapshot; it never creates an
SDK client, an order journal, an account reservation, or a writer grant.
Synthetic inputs are marked as such and therefore always produce
``execution_permission=NOT_PROVEN``.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timezone
import math
from types import MappingProxyType
from typing import Any, Deque, Dict, Iterable, Mapping, Optional, Tuple

UTC = timezone.utc
NS_PER_SECOND = 1_000_000_000


class TimingContractError(ValueError):
    """Raised when a timing fact cannot be proven from its public evidence."""


def _nonempty(value: Any, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise TimingContractError(f"{field_name} must be a non-empty string")
    return value


def _ns(value: Any, field_name: str, *, allow_none: bool = False) -> Optional[int]:
    if value is None and allow_none:
        return None
    if type(value) is not int or value < 0:
        raise TimingContractError(f"{field_name} must be a non-negative integer nanosecond value")
    return value


def _bool(value: Any, field_name: str) -> bool:
    if type(value) is not bool:
        raise TimingContractError(f"{field_name} must be a bool")
    return value


def _finite_number(value: Any, field_name: str) -> float:
    if isinstance(value, bool):
        raise TimingContractError(f"{field_name} must be finite")
    try:
        parsed = float(value)
    except (TypeError, ValueError, OverflowError) as error:
        raise TimingContractError(f"{field_name} must be finite") from error
    if not math.isfinite(parsed):
        raise TimingContractError(f"{field_name} must be finite")
    return parsed


def _aware(value: Any, field_name: str) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise TimingContractError(f"{field_name} must be timezone-aware")
    return value.astimezone(UTC)


def _tuple_strings(values: Iterable[Any], field_name: str) -> Tuple[str, ...]:
    result = tuple(_nonempty(value, field_name) for value in values)
    return result


def deadline(origin_ns: int, timeout_seconds: int | float) -> int:
    """Return an exact nanosecond deadline without accepting bool or NaN."""

    origin = _ns(origin_ns, "origin_ns")
    timeout = _finite_number(timeout_seconds, "timeout_seconds")
    if timeout <= 0 or not timeout.is_integer():
        raise TimingContractError("timeout_seconds must be a positive whole number")
    return origin + int(timeout) * NS_PER_SECOND


@dataclass(frozen=True)
class ScopeIdentity:
    """The account/candidate/session identity attached to every fact."""

    candidate_id: str
    basket_id: str
    account_fingerprint: str
    trading_day: str
    session_segment: str
    generation: int
    rules_hash: str
    clock_domain: str
    mapping_id: str
    source: str
    synthetic: bool

    def __post_init__(self) -> None:
        for name in (
            "candidate_id",
            "basket_id",
            "account_fingerprint",
            "trading_day",
            "session_segment",
            "rules_hash",
            "clock_domain",
            "mapping_id",
            "source",
        ):
            _nonempty(getattr(self, name), name)
        if type(self.generation) is not int or self.generation <= 0:
            raise TimingContractError("generation must be a positive integer")
        _bool(self.synthetic, "synthetic")

    @property
    def key(self) -> Tuple[str, ...]:
        return (
            self.candidate_id,
            self.basket_id,
            self.account_fingerprint,
            self.trading_day,
            self.session_segment,
            str(self.generation),
            self.rules_hash,
            self.clock_domain,
            self.mapping_id,
        )

    @property
    def progression_key(self) -> Tuple[int, str, str]:
        """Lifecycle order; clock domains are intentionally not compared."""

        return self.generation, self.trading_day, self.session_segment


@dataclass(frozen=True)
class ClockMapping:
    """A frozen UTC-to-monotonic mapping supplied by the evidence owner."""

    mapping_id: str
    anchor_wall_utc: datetime
    anchor_monotonic_ns: int
    clock_domain: str
    generation: int
    source: str
    error_bound_ns: int
    valid_until_ns: int
    rules_hash: str
    synthetic: bool

    def __post_init__(self) -> None:
        _nonempty(self.mapping_id, "mapping_id")
        _aware(self.anchor_wall_utc, "anchor_wall_utc")
        _ns(self.anchor_monotonic_ns, "anchor_monotonic_ns")
        _nonempty(self.clock_domain, "clock_domain")
        if type(self.generation) is not int or self.generation <= 0:
            raise TimingContractError("generation must be a positive integer")
        _nonempty(self.source, "mapping source")
        _ns(self.error_bound_ns, "error_bound_ns")
        _ns(self.valid_until_ns, "valid_until_ns")
        if self.valid_until_ns < self.anchor_monotonic_ns:
            raise TimingContractError("mapping valid_until_ns precedes its anchor")
        _nonempty(self.rules_hash, "rules_hash")
        _bool(self.synthetic, "synthetic")

    def map_wall_to_mono_ns(self, wall_utc: datetime) -> int:
        wall = _aware(wall_utc, "wall_utc")
        delta = wall - self.anchor_wall_utc.astimezone(UTC)
        return (
            self.anchor_monotonic_ns
            + delta.days * 86_400 * NS_PER_SECOND
            + delta.seconds * NS_PER_SECOND
            + delta.microseconds * 1000
        )

    def validate_pair(self, wall_utc: datetime, monotonic_ns: int) -> None:
        observed = _ns(monotonic_ns, "monotonic_ns")
        assert observed is not None
        expected = self.map_wall_to_mono_ns(wall_utc)
        if observed > self.valid_until_ns:
            raise TimingContractError("clock observation is outside mapping validity")
        if abs(observed - expected) > self.error_bound_ns:
            raise TimingContractError("clock observation exceeds frozen mapping error bound")


@dataclass(frozen=True)
class ClockObservation:
    """One typed observation in the mapping's monotonic domain."""

    monotonic_ns: int
    wall_utc: datetime
    clock_domain: str
    mapping: ClockMapping
    scope: ScopeIdentity
    source: str
    trusted: bool
    synthetic: bool
    lower_ns: Optional[int] = None
    upper_ns: Optional[int] = None

    def __post_init__(self) -> None:
        _ns(self.monotonic_ns, "monotonic_ns")
        _aware(self.wall_utc, "wall_utc")
        _nonempty(self.clock_domain, "clock_domain")
        _nonempty(self.source, "clock source")
        _bool(self.trusted, "trusted")
        _bool(self.synthetic, "synthetic")
        lower = self.monotonic_ns if self.lower_ns is None else _ns(self.lower_ns, "lower_ns")
        upper = self.monotonic_ns if self.upper_ns is None else _ns(self.upper_ns, "upper_ns")
        assert lower is not None and upper is not None
        if lower > self.monotonic_ns or self.monotonic_ns > upper:
            raise TimingContractError("clock observation bounds must contain monotonic_ns")
        object.__setattr__(self, "lower_ns", lower)
        object.__setattr__(self, "upper_ns", upper)
        if self.clock_domain != self.mapping.clock_domain:
            raise TimingContractError("clock observation domain differs from mapping")
        if self.scope.clock_domain != self.clock_domain:
            raise TimingContractError("clock observation domain differs from scope")
        if self.scope.mapping_id != self.mapping.mapping_id:
            raise TimingContractError("clock observation mapping differs from scope")
        if self.scope.generation != self.mapping.generation:
            raise TimingContractError("clock generation differs from mapping")
        if self.scope.rules_hash != self.mapping.rules_hash:
            raise TimingContractError("clock rules differ from mapping")
        if self.synthetic != self.mapping.synthetic or self.synthetic != self.scope.synthetic:
            raise TimingContractError("synthetic clock provenance is contradictory")
        self.mapping.validate_pair(self.wall_utc, self.monotonic_ns)


@dataclass(frozen=True)
class TimingPolicy:
    """Bounded engineering values inherited from D24-09/10."""

    decision_deadline_seconds: Optional[int] = None
    leg_timeout_seconds: int = 5
    basket_timeout_seconds: int = 15
    cancel_timeout_seconds: int = 5
    recovery_timeout_seconds: int = 60
    minimum_hold_seconds: int = 60
    maximum_hold_seconds: int = 900
    idle_interval_ms: int = 250
    history_capacity: int = 128

    def __post_init__(self) -> None:
        if self.decision_deadline_seconds is not None:
            if (
                type(self.decision_deadline_seconds) is not int
                or self.decision_deadline_seconds <= 0
            ):
                raise TimingContractError("decision_deadline_seconds must be a positive integer")
        for name, upper in (
            ("leg_timeout_seconds", 5),
            ("basket_timeout_seconds", 15),
            ("cancel_timeout_seconds", 5),
            ("recovery_timeout_seconds", 60),
        ):
            value = getattr(self, name)
            if type(value) is not int or value <= 0 or value > upper:
                raise TimingContractError(
                    f"{name} must be a positive integer no greater than {upper}"
                )
        if type(self.minimum_hold_seconds) is not int or self.minimum_hold_seconds < 60:
            raise TimingContractError(
                "minimum_hold_seconds may only be equal to or stricter than 60"
            )
        if (
            type(self.maximum_hold_seconds) is not int
            or self.maximum_hold_seconds <= 0
            or self.maximum_hold_seconds > 900
        ):
            raise TimingContractError(
                "maximum_hold_seconds may only be equal to or stricter than 900"
            )
        if (
            type(self.idle_interval_ms) is not int
            or self.idle_interval_ms <= 0
            or self.idle_interval_ms > 250
        ):
            raise TimingContractError("idle_interval_ms must be between 1 and 250")
        if type(self.history_capacity) is not int or self.history_capacity < 8:
            raise TimingContractError("history_capacity is too small")

    @property
    def leg_timeout_ns(self) -> int:
        return self.leg_timeout_seconds * NS_PER_SECOND

    @property
    def basket_timeout_ns(self) -> int:
        return self.basket_timeout_seconds * NS_PER_SECOND

    @property
    def cancel_timeout_ns(self) -> int:
        return self.cancel_timeout_seconds * NS_PER_SECOND

    @property
    def recovery_timeout_ns(self) -> int:
        return self.recovery_timeout_seconds * NS_PER_SECOND

    @property
    def minimum_hold_ns(self) -> int:
        return self.minimum_hold_seconds * NS_PER_SECOND

    @property
    def maximum_hold_ns(self) -> int:
        return self.maximum_hold_seconds * NS_PER_SECOND

    @property
    def idle_interval_ns(self) -> int:
        return self.idle_interval_ms * 1_000_000


@dataclass(frozen=True)
class ExecutionEvent:
    """A detached public event used only to de-duplicate a supplied snapshot."""

    event_id: str
    kind: str
    leg: str
    quantity: int
    occurred_lower_ns: int
    occurred_upper_ns: int
    received_ns: int
    terminal: bool
    source: str

    def __post_init__(self) -> None:
        _nonempty(self.event_id, "event_id")
        _nonempty(self.kind, "event kind")
        _nonempty(self.leg, "event leg")
        _nonempty(self.source, "event source")
        if type(self.quantity) is not int or self.quantity < 0:
            raise TimingContractError("event quantity must be a non-negative integer")
        lower = _ns(self.occurred_lower_ns, "occurred_lower_ns")
        upper = _ns(self.occurred_upper_ns, "occurred_upper_ns")
        received = _ns(self.received_ns, "received_ns")
        assert lower is not None and upper is not None and received is not None
        if lower > upper or received < upper:
            raise TimingContractError("event occurrence/receive bounds are inconsistent")
        _bool(self.terminal, "event terminal")

    @property
    def fingerprint(self) -> Tuple[Any, ...]:
        return (
            self.event_id,
            self.kind,
            self.leg,
            self.quantity,
            self.occurred_lower_ns,
            self.occurred_upper_ns,
            self.received_ns,
            self.terminal,
            self.source,
        )


@dataclass(frozen=True)
class ExecutionFacts:
    """Immutable SDK-owned execution summary as seen by the example."""

    scope: ScopeIdentity
    source: str
    source_kind: str
    trusted: bool
    reported_phase: str
    first_leg_intent_ns: Optional[int]
    first_basket_intent_ns: Optional[int]
    cancel_intent_ns: Optional[int]
    earliest_exposure_lower_ns: Optional[int]
    latest_complete_fill_upper_ns: Optional[int]
    complete_basket: bool
    authoritative_flat_verified: bool
    possible_exposure_qty: Optional[int]
    confirmed_qty: int
    event_ids: Tuple[str, ...]
    collection_version: str
    risk_event_origin_ns: Optional[int] = None
    events: Tuple[ExecutionEvent, ...] = ()
    unknown: bool = False
    expiry_ns: Optional[int] = None

    def __post_init__(self) -> None:
        _nonempty(self.source, "execution source")
        if self.source_kind not in {"synthetic", "sdk-public"}:
            raise TimingContractError("source_kind must be synthetic or sdk-public")
        _bool(self.trusted, "trusted")
        _nonempty(self.reported_phase, "reported_phase")
        _nonempty(self.collection_version, "collection_version")
        if self.source_kind == "synthetic" and not self.scope.synthetic:
            raise TimingContractError("synthetic facts require a synthetic scope")
        if self.source_kind == "sdk-public" and self.scope.synthetic:
            raise TimingContractError("sdk-public facts cannot use a synthetic scope")
        for name in (
            "first_leg_intent_ns",
            "first_basket_intent_ns",
            "cancel_intent_ns",
            "earliest_exposure_lower_ns",
            "latest_complete_fill_upper_ns",
            "risk_event_origin_ns",
            "expiry_ns",
        ):
            _ns(getattr(self, name), name, allow_none=True)
        if (
            type(self.complete_basket) is not bool
            or type(self.authoritative_flat_verified) is not bool
        ):
            raise TimingContractError(
                "complete_basket and authoritative_flat_verified must be bool"
            )
        if self.possible_exposure_qty is not None and (
            type(self.possible_exposure_qty) is not int or self.possible_exposure_qty < 0
        ):
            raise TimingContractError(
                "possible_exposure_qty must be a non-negative integer or None"
            )
        if type(self.confirmed_qty) is not int or self.confirmed_qty < 0:
            raise TimingContractError("confirmed_qty must be a non-negative integer")
        _bool(self.unknown, "unknown")
        ids = _tuple_strings(self.event_ids, "event_id")
        # Repeated public delivery of the same identifier is harmless; the
        # snapshot remains one immutable fact and never adds quantity twice.
        object.__setattr__(self, "event_ids", tuple(dict.fromkeys(ids)))
        events = tuple(self.events)
        by_id: Dict[str, Tuple[Any, ...]] = {}
        for event in events:
            if not isinstance(event, ExecutionEvent):
                raise TimingContractError("events must be typed ExecutionEvent values")
            previous = by_id.setdefault(event.event_id, event.fingerprint)
            if previous != event.fingerprint:
                raise TimingContractError("contradictory duplicate execution event")
        object.__setattr__(self, "events", events)
        if self.authoritative_flat_verified and (
            self.unknown or self.possible_exposure_qty is None or self.possible_exposure_qty != 0
        ):
            raise TimingContractError(
                "FLAT_VERIFIED is incompatible with unknown possible exposure"
            )

    @property
    def possible_exposure_unknown(self) -> bool:
        return (
            self.unknown or self.possible_exposure_qty is None or self.reported_phase == "UNKNOWN"
        )

    @property
    def scope_key(self) -> Tuple[str, ...]:
        return self.scope.key


@dataclass(frozen=True)
class MinuteInput:
    """One immutable closed minute offered to the timing consumer."""

    minute_id: str
    bucket_start_ns: int
    bucket_end_ns: int
    scope: ScopeIdentity
    bar_ids: Tuple[str, str, str]
    quote_cutoffs: Tuple[Tuple[str, int], ...]
    direction: str
    max_quantity: int
    invocation_id: str
    next_boundary_ns: Optional[int]
    decision_deadline_ns: Optional[int]
    entry_candidate: bool
    z_score: Optional[float]
    legal_barrier: bool
    continuation_cost_failed: bool = False
    budget_allowed: bool = True
    admission_reason: Optional[str] = None

    def __post_init__(self) -> None:
        _nonempty(self.minute_id, "minute_id")
        start = _ns(self.bucket_start_ns, "bucket_start_ns")
        end = _ns(self.bucket_end_ns, "bucket_end_ns")
        assert start is not None and end is not None
        if end <= start:
            raise TimingContractError("bucket_end_ns must be after bucket_start_ns")
        bar_ids = tuple(self.bar_ids)
        if len(bar_ids) != 3 or len(set(bar_ids)) != 3:
            raise TimingContractError("exactly three distinct bar IDs are required")
        object.__setattr__(self, "bar_ids", _tuple_strings(bar_ids, "bar_id"))
        quote_cutoffs = tuple(self.quote_cutoffs)
        if len(quote_cutoffs) != 3:
            raise TimingContractError("exactly three quote cutoffs are required")
        seen = set()
        for symbol, sequence in quote_cutoffs:
            _nonempty(symbol, "quote cutoff symbol")
            if symbol in seen or type(sequence) is not int or sequence < 0:
                raise TimingContractError("quote cutoffs must be unique non-negative integers")
            seen.add(symbol)
        object.__setattr__(
            self,
            "quote_cutoffs",
            tuple((str(symbol), sequence) for symbol, sequence in quote_cutoffs),
        )
        _nonempty(self.direction, "direction")
        if type(self.max_quantity) is not int or self.max_quantity <= 0:
            raise TimingContractError("max_quantity must be a positive integer")
        _nonempty(self.invocation_id, "invocation_id")
        _ns(self.next_boundary_ns, "next_boundary_ns", allow_none=True)
        _ns(self.decision_deadline_ns, "decision_deadline_ns", allow_none=True)
        _bool(self.entry_candidate, "entry_candidate")
        if self.z_score is not None:
            _finite_number(self.z_score, "z_score")
        _bool(self.legal_barrier, "legal_barrier")
        _bool(self.continuation_cost_failed, "continuation_cost_failed")
        _bool(self.budget_allowed, "budget_allowed")
        if self.admission_reason is not None:
            _nonempty(self.admission_reason, "admission_reason")


@dataclass(frozen=True)
class DeadlineProjection:
    name: str
    origin_ns: Optional[int]
    timeout_ns: int
    deadline_ns: Optional[int]
    expired: bool


@dataclass(frozen=True)
class TimingToken:
    token_id: str
    candidate_id: str
    minute_id: str
    bar_ids: Tuple[str, str, str]
    quote_cutoffs: Tuple[Tuple[str, int], ...]
    bucket_end_ns: int
    scope_key: Tuple[str, ...]
    direction: str
    max_quantity: int
    invocation_id: str
    expires_at_ns: int
    execution_permission: str = "NOT_PROVEN"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "token_id": self.token_id,
            "candidate_id": self.candidate_id,
            "minute_id": self.minute_id,
            "bar_ids": list(self.bar_ids),
            "quote_cutoffs": dict(self.quote_cutoffs),
            "bucket_end_ns": self.bucket_end_ns,
            "scope_key": list(self.scope_key),
            "direction": self.direction,
            "max_quantity": self.max_quantity,
            "invocation_id": self.invocation_id,
            "expires_at_ns": self.expires_at_ns,
            "execution_permission": self.execution_permission,
        }


@dataclass(frozen=True)
class TimingProjection:
    reason: str
    scope_key: Tuple[str, ...]
    reported_phase: str
    required_phase: str
    risk_action: str
    execution_permission: str
    deadlines: Mapping[str, DeadlineProjection]
    minimum_hold_deadline_ns: Optional[int]
    maximum_hold_deadline_ns: Optional[int]
    normal_exit_allowed: bool
    max_hold_due: bool
    possible_exposure_unknown: bool
    minute_consumed: bool = False
    token: Optional[TimingToken] = None
    timing_fault: Optional[str] = None
    cadence_ok: bool = True
    decision_id: Optional[str] = None
    execution_basis: Mapping[str, Any] = field(default_factory=dict)
    time_facts: Mapping[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "reason": self.reason,
            "scope_key": list(self.scope_key),
            "reported_phase": self.reported_phase,
            "required_phase": self.required_phase,
            "risk_action": self.risk_action,
            "execution_permission": self.execution_permission,
            "deadlines": {
                key: {
                    "origin_ns": value.origin_ns,
                    "timeout_ns": value.timeout_ns,
                    "deadline_ns": value.deadline_ns,
                    "expired": value.expired,
                }
                for key, value in self.deadlines.items()
            },
            "minimum_hold_deadline_ns": self.minimum_hold_deadline_ns,
            "maximum_hold_deadline_ns": self.maximum_hold_deadline_ns,
            "normal_exit_allowed": self.normal_exit_allowed,
            "max_hold_due": self.max_hold_due,
            "possible_exposure_unknown": self.possible_exposure_unknown,
            "minute_consumed": self.minute_consumed,
            "token": None if self.token is None else self.token.to_dict(),
            "timing_fault": self.timing_fault,
            "cadence_ok": self.cadence_ok,
            "decision_id": self.decision_id,
            "execution_basis": dict(self.execution_basis),
            "time_facts": dict(self.time_facts),
        }


@dataclass(frozen=True)
class CalendarEvidence:
    """Explicit segment/calendar facts used by the entry and risk gates."""

    segment_id: str
    rules_hash: str
    source: str
    seconds_to_close: int
    trading_days_to_maturity: int
    exercise_or_delivery_seconds: Optional[int] = None
    as_of_ns: Optional[int] = None
    valid_until_ns: Optional[int] = None
    exercise_or_delivery_at_ns: Optional[int] = None

    def __post_init__(self) -> None:
        _nonempty(self.segment_id, "segment_id")
        _nonempty(self.rules_hash, "rules_hash")
        _nonempty(self.source, "calendar source")
        if type(self.seconds_to_close) is not int or self.seconds_to_close < 0:
            raise TimingContractError("seconds_to_close must be a non-negative integer")
        if type(self.trading_days_to_maturity) is not int or self.trading_days_to_maturity < 0:
            raise TimingContractError("trading_days_to_maturity must be a non-negative integer")
        _ns(
            self.exercise_or_delivery_seconds,
            "exercise_or_delivery_seconds",
            allow_none=True,
        )
        as_of = _ns(self.as_of_ns, "as_of_ns", allow_none=True)
        valid_until = _ns(self.valid_until_ns, "valid_until_ns", allow_none=True)
        cutoff = _ns(
            self.exercise_or_delivery_at_ns,
            "exercise_or_delivery_at_ns",
            allow_none=True,
        )
        if valid_until is not None and as_of is not None and valid_until < as_of:
            raise TimingContractError("calendar validity precedes its observation")
        object.__setattr__(self, "as_of_ns", as_of)
        object.__setattr__(self, "valid_until_ns", valid_until)
        object.__setattr__(self, "exercise_or_delivery_at_ns", cutoff)


@dataclass(frozen=True)
class CalendarProjection:
    entry_allowed: bool
    risk_exit_due: bool
    handover_due: bool
    reason: str


def evaluate_calendar(
    evidence: Optional[CalendarEvidence],
    *,
    expected_rules_hash: str,
    now_ns: Optional[int] = None,
) -> CalendarProjection:
    if evidence is None:
        return CalendarProjection(False, True, True, "CALENDAR_EVIDENCE_MISSING")
    if evidence.rules_hash != expected_rules_hash:
        return CalendarProjection(False, True, True, "CALENDAR_RULES_MISMATCH")
    if now_ns is not None:
        now = _ns(now_ns, "calendar now_ns")
        assert now is not None
        if evidence.as_of_ns is None or evidence.valid_until_ns is None:
            return CalendarProjection(False, True, True, "CALENDAR_TIME_FACTS_MISSING")
        if now < evidence.as_of_ns or now > evidence.valid_until_ns:
            return CalendarProjection(False, True, True, "CALENDAR_EVIDENCE_STALE")
        if (
            evidence.exercise_or_delivery_at_ns is not None
            and now >= evidence.exercise_or_delivery_at_ns
        ):
            return CalendarProjection(False, True, True, "EXERCISE_OR_DELIVERY_CUTOFF")
    if evidence.trading_days_to_maturity < 5:
        return CalendarProjection(False, True, True, "MATURITY_TOO_NEAR")
    if (
        evidence.exercise_or_delivery_seconds is not None
        and evidence.exercise_or_delivery_seconds <= 0
    ):
        return CalendarProjection(False, True, True, "EXERCISE_OR_DELIVERY_CUTOFF")
    return CalendarProjection(
        entry_allowed=evidence.seconds_to_close > 1_800,
        risk_exit_due=evidence.seconds_to_close <= 600,
        handover_due=evidence.seconds_to_close <= 180,
        reason="READY" if evidence.seconds_to_close > 1_800 else "SESSION_CUTOFF",
    )


def _deadline_projection(
    name: str, origin_ns: Optional[int], timeout_ns: int, now_ns: int
) -> DeadlineProjection:
    if origin_ns is None:
        return DeadlineProjection(name, None, timeout_ns, None, False)
    deadline_ns = origin_ns + timeout_ns
    return DeadlineProjection(name, origin_ns, timeout_ns, deadline_ns, now_ns >= deadline_ns)


class TimingProjector:
    """Bounded pure read-model consumer for MF-T1 timing facts."""

    def __init__(
        self,
        *,
        scope: ScopeIdentity,
        mapping: ClockMapping,
        policy: TimingPolicy,
        audit_capacity: int = 256,
    ) -> None:
        if not isinstance(scope, ScopeIdentity) or not isinstance(mapping, ClockMapping):
            raise TimingContractError("scope and mapping are required typed values")
        if mapping.mapping_id != scope.mapping_id or mapping.clock_domain != scope.clock_domain:
            raise TimingContractError("scope and mapping identity mismatch")
        if mapping.generation != scope.generation or mapping.rules_hash != scope.rules_hash:
            raise TimingContractError("scope and mapping generation/rules mismatch")
        if mapping.synthetic != scope.synthetic:
            raise TimingContractError("scope and mapping synthetic provenance mismatch")
        if type(audit_capacity) is not int or audit_capacity < 16:
            raise TimingContractError("audit_capacity is too small")
        self.scope = scope
        self.mapping = mapping
        self.policy = policy
        self._last_mono_ns: Optional[int] = None
        self._last_idle_ns: Optional[int] = None
        self._clock_fault: Optional[str] = None
        self._minute_watermark_ns: Optional[int] = None
        self._consumed_minutes: Deque[str] = deque(maxlen=policy.history_capacity)
        self._consumed_set: set[str] = set()
        self._audit: Deque[Dict[str, Any]] = deque(maxlen=audit_capacity)
        self._cadence_failures = 0
        self._scope_floor = scope.progression_key
        self._retired_scope_keys: Deque[Tuple[str, ...]] = deque(maxlen=audit_capacity)
        self._retired_scope_set: set[Tuple[str, ...]] = set()
        self._last_facts: Optional[ExecutionFacts] = None
        self._remember_scope(scope)

    @property
    def clock_fault(self) -> bool:
        return self._clock_fault is not None

    @property
    def timing_fault(self) -> Optional[str]:
        return self._clock_fault

    @property
    def audit(self) -> Tuple[Mapping[str, Any], ...]:
        return tuple(MappingProxyType(dict(item)) for item in self._audit)

    def _latch(self, reason: str) -> None:
        if self._clock_fault is None:
            self._clock_fault = reason
            self._audit.append({"kind": "TIMING_FAULT", "reason": reason})

    def _remember_scope(self, scope: ScopeIdentity) -> None:
        key = scope.key
        if key in self._retired_scope_set:
            return
        if len(self._retired_scope_keys) == self._retired_scope_keys.maxlen:
            self._retired_scope_set.discard(self._retired_scope_keys.popleft())
        self._retired_scope_keys.append(key)
        self._retired_scope_set.add(key)

    def _validate_scope(self, scope: ScopeIdentity) -> bool:
        return scope == self.scope

    def _observe(self, observation: ClockObservation) -> Optional[str]:
        if observation.scope != self.scope:
            return "SCOPE_MISMATCH"
        if observation.clock_domain != self.mapping.clock_domain:
            return "CLOCK_DOMAIN_MISMATCH"
        if observation.mapping != self.mapping:
            return "CLOCK_MAPPING_MISMATCH"
        if not observation.trusted:
            return "CLOCK_UNTRUSTED"
        if self._last_mono_ns is not None and observation.monotonic_ns < self._last_mono_ns:
            self._latch("CLOCK_REGRESSION")
            return "CLOCK_REGRESSION"
        self._last_mono_ns = observation.monotonic_ns
        self._audit.append(
            {
                "kind": "CLOCK_OBSERVATION",
                "monotonic_ns": observation.monotonic_ns,
                "domain": observation.clock_domain,
            }
        )
        return None

    @staticmethod
    def _execution_basis(
        facts: ExecutionFacts,
        now: Optional[ClockObservation],
        *,
        channel: str,
        minute: Optional[MinuteInput] = None,
        calendar: Optional[CalendarEvidence] = None,
    ) -> Tuple[Mapping[str, Any], Mapping[str, Any]]:
        """Return the auditable source and bounded time facts for a projection."""

        basis = {
            "channel": channel,
            "source": facts.source,
            "source_kind": facts.source_kind,
            "trusted": facts.trusted,
            "synthetic": facts.scope.synthetic,
            "scope_key": list(facts.scope.key),
            "clock_domain": facts.scope.clock_domain,
            "mapping_id": facts.scope.mapping_id,
            "execution_permission": "NOT_PROVEN",
        }
        time_facts: Dict[str, Any] = {
            "now_lower_ns": None if now is None else now.lower_ns,
            "now_observed_ns": None if now is None else now.monotonic_ns,
            "now_upper_ns": None if now is None else now.upper_ns,
            "facts_scope_key": list(facts.scope.key),
            "first_leg_intent_ns": facts.first_leg_intent_ns,
            "first_basket_intent_ns": facts.first_basket_intent_ns,
            "earliest_exposure_lower_ns": facts.earliest_exposure_lower_ns,
            "latest_complete_fill_upper_ns": facts.latest_complete_fill_upper_ns,
            "minute_id": None if minute is None else minute.minute_id,
            "minute_bucket_end_ns": None if minute is None else minute.bucket_end_ns,
            "calendar_as_of_ns": None if calendar is None else calendar.as_of_ns,
            "calendar_valid_until_ns": None if calendar is None else calendar.valid_until_ns,
            "exercise_or_delivery_at_ns": (
                None if calendar is None else calendar.exercise_or_delivery_at_ns
            ),
        }
        return MappingProxyType(basis), MappingProxyType(time_facts)

    @staticmethod
    def _has_unresolved_obligation(facts: ExecutionFacts) -> bool:
        if facts.authoritative_flat_verified:
            return False
        return (
            facts.possible_exposure_unknown
            or not facts.complete_basket
            and (
                facts.confirmed_qty > 0
                or facts.first_leg_intent_ns is not None
                or facts.first_basket_intent_ns is not None
                or facts.earliest_exposure_lower_ns is not None
            )
        )

    def _deadlines(self, facts: ExecutionFacts, now_ns: int) -> Dict[str, DeadlineProjection]:
        leg = _deadline_projection(
            "leg", facts.first_leg_intent_ns, self.policy.leg_timeout_ns, now_ns
        )
        basket = _deadline_projection(
            "basket", facts.first_basket_intent_ns, self.policy.basket_timeout_ns, now_ns
        )
        cancel = _deadline_projection(
            "cancel", facts.cancel_intent_ns, self.policy.cancel_timeout_ns, now_ns
        )
        recovery_origin = facts.risk_event_origin_ns
        expired_origins = [
            value.deadline_ns
            for value in (leg, basket, cancel)
            if value.expired and value.deadline_ns is not None
        ]
        if expired_origins:
            recovery_origin = (
                min([recovery_origin, *expired_origins])
                if recovery_origin is not None
                else min(expired_origins)
            )
        recovery = _deadline_projection(
            "recovery", recovery_origin, self.policy.recovery_timeout_ns, now_ns
        )
        return {"leg": leg, "basket": basket, "cancel": cancel, "recovery": recovery}

    def _blocked(
        self,
        facts: ExecutionFacts,
        reason: str,
        *,
        timing_fault: Optional[str] = None,
        minute_consumed: bool = False,
        cadence_ok: bool = True,
        now: Optional[ClockObservation] = None,
        minute: Optional[MinuteInput] = None,
        calendar: Optional[CalendarEvidence] = None,
    ) -> TimingProjection:
        basis, time_facts = self._execution_basis(
            facts, now, channel="blocked", minute=minute, calendar=calendar
        )
        return TimingProjection(
            reason=reason,
            scope_key=facts.scope.key,
            reported_phase=facts.reported_phase,
            required_phase=(
                "HALTED_MONITORING" if facts.possible_exposure_unknown else facts.reported_phase
            ),
            risk_action="HANDOVER" if facts.possible_exposure_unknown else "NONE",
            execution_permission="NOT_PROVEN",
            deadlines=MappingProxyType({}),
            minimum_hold_deadline_ns=None,
            maximum_hold_deadline_ns=None,
            normal_exit_allowed=False,
            max_hold_due=False,
            possible_exposure_unknown=facts.possible_exposure_unknown,
            minute_consumed=minute_consumed,
            timing_fault=timing_fault,
            cadence_ok=cadence_ok,
            execution_basis=basis,
            time_facts=time_facts,
        )

    def project(
        self,
        facts: ExecutionFacts,
        now: ClockObservation,
        *,
        minute: Optional[MinuteInput] = None,
        calendar: Optional[CalendarEvidence] = None,
    ) -> TimingProjection:
        if not isinstance(facts, ExecutionFacts) or not isinstance(now, ClockObservation):
            raise TimingContractError(
                "project requires typed execution facts and clock observation"
            )
        if minute is not None and not isinstance(minute, MinuteInput):
            raise TimingContractError("minute must be a typed MinuteInput value")
        if facts.scope != self.scope:
            return self._blocked(facts, "SCOPE_MISMATCH", now=now, minute=minute, calendar=calendar)
        if minute is not None and minute.scope != self.scope:
            return self._blocked(facts, "SCOPE_MISMATCH", now=now, minute=minute, calendar=calendar)
        if not facts.trusted:
            return self._blocked(
                facts, "EXECUTION_FACTS_UNTRUSTED", now=now, minute=minute, calendar=calendar
            )
        if facts.expiry_ns is not None and now.monotonic_ns >= facts.expiry_ns:
            return self._blocked(
                facts, "EXECUTION_FACTS_EXPIRED", now=now, minute=minute, calendar=calendar
            )
        if self._clock_fault is not None:
            return self._blocked(
                facts,
                self._clock_fault,
                timing_fault=self._clock_fault,
                now=now,
                minute=minute,
                calendar=calendar,
            )
        observation_reason = self._observe(now)
        if observation_reason is not None:
            if observation_reason == "CLOCK_REGRESSION":
                return self._blocked(
                    facts,
                    observation_reason,
                    timing_fault=observation_reason,
                    now=now,
                    minute=minute,
                    calendar=calendar,
                )
            return self._blocked(
                facts,
                observation_reason,
                timing_fault=observation_reason,
                now=now,
                minute=minute,
                calendar=calendar,
            )
        self._last_facts = facts
        now_lower_ns = now.lower_ns
        now_upper_ns = now.upper_ns
        assert now_lower_ns is not None and now_upper_ns is not None
        calendar_projection = (
            evaluate_calendar(
                calendar, expected_rules_hash=self.scope.rules_hash, now_ns=now_upper_ns
            )
            if calendar is not None
            else None
        )
        now_ns = now_upper_ns
        projections = self._deadlines(facts, now_ns)
        minimum_hold = (
            None
            if facts.latest_complete_fill_upper_ns is None
            else facts.latest_complete_fill_upper_ns + self.policy.minimum_hold_ns
        )
        maximum_hold = (
            None
            if facts.earliest_exposure_lower_ns is None
            else facts.earliest_exposure_lower_ns + self.policy.maximum_hold_ns
        )
        max_due = maximum_hold is not None and now_ns >= maximum_hold
        recovery_due = projections["recovery"].expired
        normal_allowed = (
            facts.complete_basket
            and not facts.possible_exposure_unknown
            and minimum_hold is not None
            and now_lower_ns >= minimum_hold
        )
        if minute is not None:
            normal_allowed = normal_allowed and minute.legal_barrier
            if facts.latest_complete_fill_upper_ns is not None:
                normal_allowed = normal_allowed and (
                    minute.bucket_end_ns > facts.latest_complete_fill_upper_ns
                )
            if minute.z_score is not None:
                normal_allowed = normal_allowed and (
                    abs(minute.z_score) <= 0.5 or minute.continuation_cost_failed
                )
        calendar_reason = None if calendar_projection is None else calendar_projection.reason
        if calendar_projection is not None and not calendar_projection.entry_allowed:
            normal_allowed = False
        required_phase = facts.reported_phase
        risk_action = "NONE"
        reason = calendar_reason or "READY"
        if facts.possible_exposure_unknown and not facts.authoritative_flat_verified:
            required_phase = "HALTED_MONITORING"
            risk_action = "HANDOVER"
            reason = "EXECUTION_FACTS_UNKNOWN"
        elif recovery_due and not facts.authoritative_flat_verified:
            required_phase = "HALTED_MONITORING"
            risk_action = "HANDOVER"
            reason = "RECOVERY_DEADLINE_EXPIRED"
        elif max_due:
            required_phase = "RISK_EXIT_DUE"
            risk_action = "RISK_REDUCING"
            reason = "MAX_HOLD_EXPIRED"
        elif projections["basket"].expired and not facts.complete_basket:
            required_phase = "RECOVERY_REQUIRED"
            risk_action = "RISK_REDUCING"
            reason = "BASKET_DEADLINE_EXPIRED"
        elif projections["leg"].expired and not facts.complete_basket:
            required_phase = "RECOVERY_REQUIRED"
            risk_action = "RISK_REDUCING"
            reason = "LEG_DEADLINE_EXPIRED"
        elif calendar_projection is not None and calendar_projection.risk_exit_due:
            required_phase = "RISK_EXIT_DUE"
            risk_action = "RISK_REDUCING"
            reason = calendar_projection.reason
        if risk_action != "NONE":
            normal_allowed = False
        basis, time_facts = self._execution_basis(
            facts, now, channel="project", minute=minute, calendar=calendar
        )
        return TimingProjection(
            reason=reason,
            scope_key=self.scope.key,
            reported_phase=facts.reported_phase,
            required_phase=required_phase,
            risk_action=risk_action,
            execution_permission="NOT_PROVEN",
            deadlines=MappingProxyType(projections),
            minimum_hold_deadline_ns=minimum_hold,
            maximum_hold_deadline_ns=maximum_hold,
            normal_exit_allowed=normal_allowed,
            max_hold_due=max_due,
            possible_exposure_unknown=facts.possible_exposure_unknown,
            execution_basis=basis,
            time_facts=time_facts,
        )

    def consume_minute(
        self,
        minute: MinuteInput,
        facts: ExecutionFacts,
        now: ClockObservation,
        *,
        calendar: Optional[CalendarEvidence] = None,
    ) -> TimingProjection:
        """Consume one closed minute; all outcomes retire its ordinary action."""

        if minute.scope != self.scope or facts.scope != self.scope:
            return self._blocked(facts, "SCOPE_MISMATCH")
        if minute.minute_id in self._consumed_set:
            base = self.project(facts, now, minute=minute, calendar=calendar)
            return TimingProjection(
                **{**base.__dict__, "reason": "MINUTE_ALREADY_CONSUMED", "minute_consumed": False}
            )
        if (
            self._minute_watermark_ns is not None
            and minute.bucket_end_ns <= self._minute_watermark_ns
        ):
            return self._blocked(facts, "MINUTE_RETIRED")
        base = self.project(facts, now, minute=minute, calendar=calendar)
        if base.timing_fault is not None or base.risk_action != "NONE" or base.reason != "READY":
            # A rejected projection is terminal for this minute.  Admission
            # must never reinterpret an execution, clock, calendar, or risk
            # rejection as permission to issue an ordinary token.
            return TimingProjection(
                **{**base.__dict__, "minute_consumed": True, "token": None, "decision_id": None}
            )
        self._consumed_minutes.append(minute.minute_id)
        self._consumed_set.add(minute.minute_id)
        while len(self._consumed_set) > self._consumed_minutes.maxlen:
            self._consumed_set.discard(self._consumed_minutes.popleft())
        self._minute_watermark_ns = minute.bucket_end_ns
        reason = base.reason
        token: Optional[TimingToken] = None
        if base.max_hold_due or base.required_phase in {"HALTED_MONITORING", "RECOVERY_REQUIRED"}:
            reason = base.reason
        elif facts.complete_basket:
            reason = (
                "NORMAL_EXIT_PROPOSAL" if base.normal_exit_allowed else "HOLD_MINIMUM_NOT_REACHED"
            )
        elif not minute.legal_barrier:
            reason = "MINUTE_BARRIER_REJECTED"
        elif minute.admission_reason is not None:
            reason = minute.admission_reason
        elif (
            calendar is not None
            and not evaluate_calendar(
                calendar,
                expected_rules_hash=self.scope.rules_hash,
                now_ns=now.upper_ns,
            ).entry_allowed
        ):
            reason = "CALENDAR_ENTRY_REJECTED"
        elif not minute.entry_candidate:
            reason = "NO_ENTRY_CANDIDATE"
        elif not facts.authoritative_flat_verified or facts.possible_exposure_unknown:
            reason = "ACTIVE_SCOPE_NO_ENTRY"
        elif not minute.budget_allowed:
            reason = "BUDGET_REJECTED"
        elif self.policy.decision_deadline_seconds is None or minute.decision_deadline_ns is None:
            reason = "DECISION_DEADLINE_MISSING"
        elif minute.next_boundary_ns is None:
            reason = "MINUTE_BOUNDARY_MISSING"
        else:
            expiry = min(minute.next_boundary_ns, minute.decision_deadline_ns)
            if now.monotonic_ns >= expiry:
                reason = "DECISION_TOKEN_EXPIRED"
            else:
                token = TimingToken(
                    token_id=f"{self.scope.candidate_id}:{minute.minute_id}:{minute.invocation_id}",
                    candidate_id=self.scope.candidate_id,
                    minute_id=minute.minute_id,
                    bar_ids=minute.bar_ids,
                    quote_cutoffs=minute.quote_cutoffs,
                    bucket_end_ns=minute.bucket_end_ns,
                    scope_key=self.scope.key,
                    direction=minute.direction,
                    max_quantity=minute.max_quantity,
                    invocation_id=minute.invocation_id,
                    expires_at_ns=expiry,
                )
                reason = "TOKEN_READY_NOT_PROVEN"
        return TimingProjection(
            **{
                **base.__dict__,
                "reason": reason,
                "minute_consumed": True,
                "token": token,
                "decision_id": None if token is None else token.token_id,
            }
        )

    def notify_idle(
        self,
        facts: ExecutionFacts,
        now: ClockObservation,
        *,
        calendar: Optional[CalendarEvidence] = None,
    ) -> TimingProjection:
        """Project risk on a no-bar callback without creating ordinary entry."""

        cadence_ok = self._last_idle_ns is None or (
            now.monotonic_ns - self._last_idle_ns <= self.policy.idle_interval_ns
        )
        if (
            self._last_idle_ns is not None
            and now.monotonic_ns - self._last_idle_ns > self.policy.idle_interval_ns
        ):
            self._cadence_failures += 1
        self._last_idle_ns = now.monotonic_ns
        result = self.project(facts, now, calendar=calendar)
        # No-bar/no-tick callbacks do not prove a completed minute barrier.
        # They may trigger risk-reducing action, but can never authorize a
        # normal exit from cached facts.
        result = TimingProjection(
            **{
                **result.__dict__,
                "normal_exit_allowed": False,
                "execution_basis": MappingProxyType(
                    {**dict(result.execution_basis), "channel": "idle_risk_only"}
                ),
            }
        )
        if not cadence_ok and result.timing_fault is None:
            return TimingProjection(
                **{**result.__dict__, "reason": "IDLE_CADENCE_LATE", "cadence_ok": False}
            )
        return result

    def reset_scope(self, scope: ScopeIdentity, mapping: ClockMapping) -> None:
        """Move to a declared newer scope; an old scope cannot be replayed."""

        if not isinstance(scope, ScopeIdentity) or not isinstance(mapping, ClockMapping):
            raise TimingContractError("scope and mapping are required typed values")
        if (
            scope.candidate_id != self.scope.candidate_id
            or scope.account_fingerprint != self.scope.account_fingerprint
        ):
            raise TimingContractError("candidate/account identity cannot change through reset")
        if scope.key in self._retired_scope_set:
            raise TimingContractError("SCOPE_RESET_REQUIRED: scope has already been retired")
        if scope.progression_key < self._scope_floor:
            raise TimingContractError("SCOPE_RESET_REQUIRED: scope is not newer than retired scope")
        if (
            scope.progression_key == self._scope_floor
            and scope.clock_domain == self.scope.clock_domain
        ):
            raise TimingContractError(
                "SCOPE_RESET_REQUIRED: same lifecycle scope cannot be replayed"
            )
        if mapping.mapping_id != scope.mapping_id or mapping.clock_domain != scope.clock_domain:
            raise TimingContractError("scope and mapping identity mismatch")
        if mapping.generation != scope.generation or mapping.rules_hash != scope.rules_hash:
            raise TimingContractError("scope and mapping generation/rules mismatch")
        if mapping.synthetic != scope.synthetic:
            raise TimingContractError("scope and mapping synthetic provenance mismatch")
        if self._last_facts is not None and self._has_unresolved_obligation(self._last_facts):
            raise TimingContractError(
                "UNRESOLVED_EXECUTION_OBLIGATION: scope reset cannot clear active risk"
            )
        self._remember_scope(self.scope)
        self.scope = scope
        self.mapping = mapping
        self._scope_floor = scope.progression_key
        self._remember_scope(scope)
        self._last_mono_ns = None
        self._last_idle_ns = None
        self._clock_fault = None
        self._minute_watermark_ns = None
        self._consumed_minutes.clear()
        self._consumed_set.clear()
        self._last_facts = None
        self._audit.append({"kind": "SCOPE_RESET", "scope": list(scope.key)})

    def build_report(self) -> Dict[str, Any]:
        return {
            "scope": list(self.scope.key),
            "clock_fault": self._clock_fault,
            "cadence_failures": self._cadence_failures,
            "minute_watermark_ns": self._minute_watermark_ns,
            "consumed_minute_count": len(self._consumed_set),
            "audit": list(self._audit),
            "execution_permission": "NOT_PROVEN",
            "execution_basis": {
                "scope_key": list(self.scope.key),
                "clock_domain": self.scope.clock_domain,
                "mapping_id": self.scope.mapping_id,
                "source": "typed_execution_facts_and_clock_observation",
                "synthetic": self.scope.synthetic,
                "permission": "NOT_PROVEN",
            },
            "time_facts_trace": list(self._audit),
        }


# One descriptive public name is enough for callers; this alias preserves the
# noun used in the acceptance text without introducing a second implementation.
ExecutionTimingProjector = TimingProjector


__all__ = [
    "CalendarEvidence",
    "CalendarProjection",
    "ClockMapping",
    "ClockObservation",
    "ExecutionEvent",
    "ExecutionFacts",
    "ExecutionTimingProjector",
    "MinuteInput",
    "NS_PER_SECOND",
    "ScopeIdentity",
    "TimingContractError",
    "TimingPolicy",
    "TimingProjection",
    "TimingProjector",
    "TimingToken",
    "deadline",
    "evaluate_calendar",
]
