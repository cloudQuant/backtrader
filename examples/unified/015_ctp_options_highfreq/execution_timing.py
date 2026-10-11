"""Immutable, zero-write HF-T1 timing projections.

The Iteration 25 replay has no SDK execution-fact source.  This module keeps
that boundary explicit: it can project deadlines from a caller-supplied,
immutable evidence snapshot, but it never constructs a client, sends or
cancels an order, writes a journal, or produces an execution permission.

``project_timing`` is the small compatibility helper used by the existing
offline replay.  ``TimingProjector`` is the stricter local synthetic-fixture
path used to exercise the HF-T1 contract.  Synthetic evidence is deliberately
marked and remains a local proposal even when every synthetic fact is valid.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Iterable, Mapping

LEG_TTL_NS = 1_000_000_000
UNHEDGED_TTL_NS = 3_000_000_000
HOLDING_TTL_NS = 60_000_000_000
IDLE_INTERVAL_NS = 50_000_000

_FACT_TYPES = frozenset(
    {
        "durable_intent",
        "send",
        "ack",
        "cancel",
        "terminal",
        "confirmed",
        "fill",
        "per_leg",
        "aggregate",
        "hold",
    }
)
_EXPOSURE_FACT_TYPES = frozenset({"durable_intent", "send", "confirmed", "fill"})
_CONFIRMATION_FACT_TYPES = frozenset({"confirmed", "fill"})
_CALLBACKS = frozenset({"tick", "next", "bar", "idle"})


class TimingContractError(ValueError):
    """Raised only for malformed local timing-contract construction."""


def _identity(value: object) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _strict_int(value: object, *, name: str, nonnegative: bool = False) -> int:
    if type(value) is not int or (nonnegative and value < 0):
        qualifier = "non-negative " if nonnegative else ""
        raise TimingContractError(f"{name} must be a strict {qualifier}integer")
    return value


def _utc_text(value: object, *, name: str) -> str:
    if not _identity(value):
        raise TimingContractError(f"{name} must be a non-empty UTC timestamp")
    text = str(value)
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError as exc:
        raise TimingContractError(f"{name} must be an ISO-8601 UTC timestamp") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise TimingContractError(f"{name} must include a UTC offset")
    return text


def _alias_pairs(value: object, *, name: str) -> tuple[tuple[str, str], ...]:
    if value is None:
        return ()
    if isinstance(value, Mapping):
        items = tuple(value.items())
    else:
        try:
            items = tuple(value)  # type: ignore[arg-type]
        except TypeError as exc:
            raise TimingContractError(f"{name} must be a mapping or pair sequence") from exc
    result: list[tuple[str, str]] = []
    seen: set[str] = set()
    for item in items:
        if not isinstance(item, (tuple, list)) or len(item) != 2:
            raise TimingContractError(f"{name} entries must be two-item pairs")
        key, item_value = item
        if not _identity(key) or not _identity(item_value) or str(key) in seen:
            raise TimingContractError(f"{name} contains an invalid or duplicate alias")
        seen.add(str(key))
        result.append((str(key), str(item_value)))
    return tuple(sorted(result))


@dataclass(frozen=True)
class TimingScope:
    """The exact provider and CTP identity domain for one timing projection."""

    provider_id: str
    source_id: str
    environment: str
    account_fingerprint: str
    trading_day: str
    connection_generation: int
    subscription_epoch: int
    rules_hash: str
    candidate_id: str
    clock_domain_id: str
    boot_id: str
    calendar_source: str
    synthetic: bool

    def __post_init__(self) -> None:
        for name in (
            "provider_id",
            "source_id",
            "environment",
            "account_fingerprint",
            "trading_day",
            "rules_hash",
            "candidate_id",
            "clock_domain_id",
            "boot_id",
            "calendar_source",
        ):
            if not _identity(getattr(self, name)):
                raise TimingContractError(f"TimingScope.{name} must be non-empty")
        if type(self.connection_generation) is not int or self.connection_generation <= 0:
            raise TimingContractError("TimingScope.connection_generation must be positive")
        if type(self.subscription_epoch) is not int or self.subscription_epoch <= 0:
            raise TimingContractError("TimingScope.subscription_epoch must be positive")
        if type(self.synthetic) is not bool:
            raise TimingContractError("TimingScope.synthetic must be boolean")

    @property
    def scope_id(self) -> str:
        """Stable exact identity; values are not normalized or substituted."""

        return "|".join(
            (
                self.environment,
                self.account_fingerprint,
                self.trading_day,
                str(self.connection_generation),
                str(self.subscription_epoch),
                self.rules_hash,
                self.candidate_id,
                self.clock_domain_id,
                self.boot_id,
            )
        )


@dataclass(frozen=True)
class TimingClock:
    """Bounded same-domain time evidence supplied by a provider.

    Wall fields are retained for audit only. Deadline comparisons use
    ``now_upper_ns`` and frozen monotonic origins; no monotonic value is ever
    derived from wall time.
    """

    scope: TimingScope
    source_id: str
    now_lower_ns: int
    now_upper_ns: int
    wall_utc: str
    anchor_wall_utc: str
    anchor_monotonic_ns: int
    error_bound_ns: int
    valid_until_ns: int
    trusted: bool
    synthetic: bool

    def __post_init__(self) -> None:
        if not isinstance(self.scope, TimingScope):
            raise TimingContractError("TimingClock.scope must be a TimingScope")
        if not _identity(self.source_id) or self.source_id != self.scope.source_id:
            raise TimingContractError("TimingClock source must match the exact scope source")
        lower = _strict_int(self.now_lower_ns, name="TimingClock.now_lower_ns", nonnegative=True)
        upper = _strict_int(self.now_upper_ns, name="TimingClock.now_upper_ns", nonnegative=True)
        anchor = _strict_int(
            self.anchor_monotonic_ns, name="TimingClock.anchor_monotonic_ns", nonnegative=True
        )
        error = _strict_int(
            self.error_bound_ns, name="TimingClock.error_bound_ns", nonnegative=True
        )
        valid_until = _strict_int(
            self.valid_until_ns, name="TimingClock.valid_until_ns", nonnegative=True
        )
        if lower > upper or upper - lower > error or valid_until < upper:
            raise TimingContractError("TimingClock bounds or validity window are inconsistent")
        _utc_text(self.wall_utc, name="TimingClock.wall_utc")
        _utc_text(self.anchor_wall_utc, name="TimingClock.anchor_wall_utc")
        if type(self.trusted) is not bool or type(self.synthetic) is not bool:
            raise TimingContractError("TimingClock trust and synthetic flags must be boolean")
        if self.synthetic != self.scope.synthetic:
            raise TimingContractError("TimingClock synthetic flag must match the exact scope")
        object.__setattr__(self, "now_lower_ns", lower)
        object.__setattr__(self, "now_upper_ns", upper)
        object.__setattr__(self, "anchor_monotonic_ns", anchor)
        object.__setattr__(self, "error_bound_ns", error)
        object.__setattr__(self, "valid_until_ns", valid_until)


@dataclass(frozen=True)
class OrderAssociation:
    """Observed order aliases for one exact intent/leg, never caller-invented."""

    intent_id: str
    decision_id: str
    basket_id: str
    cycle_id: str
    leg_id: str
    order_id: str
    aliases: tuple[tuple[str, str], ...] = ()

    def __post_init__(self) -> None:
        for name in ("intent_id", "decision_id", "basket_id", "cycle_id", "leg_id", "order_id"):
            if not _identity(getattr(self, name)):
                raise TimingContractError(f"OrderAssociation.{name} must be non-empty")
        object.__setattr__(
            self, "aliases", _alias_pairs(self.aliases, name="OrderAssociation.aliases")
        )

    def matches(self, fact: "TimingFact") -> bool:
        """Strict equality on every identity field and the full alias set.

        A partial alias overlap never matches: the observed submission
        aliases must equal the immutable association exactly.
        """
        if (
            fact.intent_id != self.intent_id
            or fact.decision_id != self.decision_id
            or fact.basket_id != self.basket_id
            or fact.cycle_id != self.cycle_id
            or fact.leg_id != self.leg_id
            or fact.order_id != self.order_id
        ):
            return False
        # This strict path cannot silently accept a partial alias set: each
        # observed submission alias is part of the immutable association.
        return fact.order_aliases == self.aliases


@dataclass(frozen=True)
class TimingFact:
    """Candidate-local immutable input used by timing projections.

    The original short field set remains for the existing replay helper. The
    additional fields are required by ``TimingProjector``'s strict local
    synthetic path, where an opaque scope string is deliberately insufficient.
    """

    fact_id: str
    fact_type: str
    intent_id: str
    provider_id: str
    source_id: str
    scope_id: str
    clock_domain_id: str
    order_id: str
    leg_id: str
    origin_lower_ns: int
    scope: TimingScope | None = None
    decision_id: str = ""
    basket_id: str = ""
    cycle_id: str = ""
    exchange_id: str = ""
    trade_id: str = ""
    direction: str = ""
    offset: str = ""
    quantity: int | None = None
    cumulative_quantity: int | None = None
    origin_upper_ns: int | None = None
    received_ns: int | None = None
    order_aliases: tuple[tuple[str, str], ...] = ()
    synthetic: bool = False

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "order_aliases", _alias_pairs(self.order_aliases, name="TimingFact.order_aliases")
        )


@dataclass(frozen=True)
class TimingSnapshot:
    """One bounded provider read; it contains no execution handle."""

    scope: TimingScope
    clock: TimingClock
    facts: tuple[TimingFact, ...]
    legal_executable_quote: bool = False
    calendar_seconds_until_close: int | None = None
    stop_requested: bool = False

    def __post_init__(self) -> None:
        if not isinstance(self.scope, TimingScope) or not isinstance(self.clock, TimingClock):
            raise TimingContractError("TimingSnapshot requires an exact scope and clock")
        if self.clock.scope != self.scope:
            raise TimingContractError(
                "TimingSnapshot clock scope must exactly match snapshot scope"
            )
        try:
            facts = tuple(self.facts)
        except TypeError as exc:
            raise TimingContractError("TimingSnapshot.facts must be iterable") from exc
        if any(not isinstance(fact, TimingFact) for fact in facts):
            raise TimingContractError("TimingSnapshot facts must be TimingFact instances")
        if type(self.legal_executable_quote) is not bool or type(self.stop_requested) is not bool:
            raise TimingContractError("TimingSnapshot flags must be boolean")
        if self.calendar_seconds_until_close is not None:
            _strict_int(
                self.calendar_seconds_until_close,
                name="TimingSnapshot.calendar_seconds_until_close",
                nonnegative=True,
            )
        object.__setattr__(self, "facts", facts)


@dataclass(frozen=True)
class RiskActionProposal:
    """A non-executable action projection."""

    action: str
    reason: str
    origin_lower_ns: int | None
    now_upper_ns: int | None
    native_write_eligible: bool = False


@dataclass(frozen=True)
class TimingProjection:
    """Immutable HF-T1 result; no field authorizes an external write."""

    clock_trusted: bool
    admissible_fact_ids: tuple[str, ...]
    uncertain_fact_ids: tuple[str, ...]
    origin_lower_ns: int | None
    confirmed: bool
    per_leg_expired: tuple[str, ...]
    aggregate_expired: bool
    hold_expired: bool
    idle_overdue: bool
    expired_reasons: tuple[str, ...]
    protection_required: bool
    native_write_eligible: bool
    proposals: tuple[RiskActionProposal, ...]
    exposure_origin_lower_ns: int | None = None
    status: str = "OFFLINE_SIGNAL_ONLY"
    reason: str = "NO_SCOPED_EXECUTION_FACTS"
    callback: str = ""
    risk_projection_available: bool = False
    ordinary_entry_allowed: bool = False
    normal_exit_allowed: bool = False
    confirmed_quantities: tuple[tuple[str, int], ...] = ()
    unresolved_exposure: bool = False
    quarantined_fact_ids: tuple[str, ...] = ()
    audit_fact_ids: tuple[str, ...] = ()
    calendar_status: str = "CALENDAR_REQUIRED"


def _proposal(action: str, reason: str, origin: int | None, now: int | None) -> RiskActionProposal:
    return RiskActionProposal(
        action=action,
        reason=reason,
        origin_lower_ns=origin,
        now_upper_ns=now,
        native_write_eligible=False,
    )


def _fact_is_admissible(
    fact: TimingFact,
    *,
    provider_id: str,
    source_id: str,
    scope_id: str,
    clock_domain_id: str,
    intent_id: str,
) -> bool:
    return (
        isinstance(fact, TimingFact)
        and fact.fact_type in _FACT_TYPES
        and all(
            _identity(value)
            for value in (
                fact.fact_id,
                fact.intent_id,
                fact.provider_id,
                fact.source_id,
                fact.scope_id,
                fact.clock_domain_id,
                fact.order_id,
                fact.leg_id,
                provider_id,
                source_id,
                scope_id,
                clock_domain_id,
                intent_id,
            )
        )
        and fact.intent_id == intent_id
        and fact.provider_id == provider_id
        and fact.source_id == source_id
        and fact.scope_id == scope_id
        and fact.clock_domain_id == clock_domain_id
        and type(fact.origin_lower_ns) is int
        and fact.origin_lower_ns > 0
    )


def project_timing(
    facts: Iterable[TimingFact],
    *,
    now_upper_ns: int | None,
    expected_provider_id: str,
    expected_source_id: str,
    expected_scope_id: str,
    expected_clock_domain_id: str,
    intent_id: str,
    leg_ids: Iterable[str],
    last_idle_lower_ns: int | None,
) -> TimingProjection:
    """Compatibility projection for the existing OFFLINE_SIGNAL_ONLY replay.

    It intentionally has no state, so it must never create a runtime deadline.
    The stricter ``TimingProjector`` freezes origins across observations and is
    the only local fixture path that accepts a rich scope.
    """

    fact_list = tuple(facts)
    admissible = tuple(
        sorted(
            (
                fact
                for fact in fact_list
                if _fact_is_admissible(
                    fact,
                    provider_id=expected_provider_id,
                    source_id=expected_source_id,
                    scope_id=expected_scope_id,
                    clock_domain_id=expected_clock_domain_id,
                    intent_id=intent_id,
                )
            ),
            key=lambda fact: fact.fact_id,
        )
    )
    admissible_ids = tuple(fact.fact_id for fact in admissible)
    uncertain_ids = tuple(
        sorted(fact.fact_id for fact in fact_list if fact.fact_id not in admissible_ids)
    )
    clock_trusted = type(now_upper_ns) is int and now_upper_ns > 0
    leg_values = tuple(str(leg_id) for leg_id in leg_ids)

    durable: dict[str, int] = {}
    sends: dict[str, int] = {}
    exposure_candidates: list[int] = []
    for fact in admissible:
        if fact.fact_type == "durable_intent":
            durable[fact.leg_id] = min(
                durable.get(fact.leg_id, fact.origin_lower_ns), fact.origin_lower_ns
            )
        elif fact.fact_type == "send":
            sends[fact.leg_id] = min(
                sends.get(fact.leg_id, fact.origin_lower_ns), fact.origin_lower_ns
            )
        if fact.fact_type in _EXPOSURE_FACT_TYPES:
            exposure_candidates.append(fact.origin_lower_ns)
    # A proved send is the initial per-leg origin if present; otherwise the
    # earlier durable intent is used. Basket/holding use their own earliest
    # possible-exposure lower bound and never inherit a later send origin.
    leg_origins = {leg_id: sends.get(leg_id, durable.get(leg_id)) for leg_id in leg_values}
    per_leg_origin = min(
        (value for value in leg_origins.values() if value is not None), default=None
    )
    exposure_origin = min(exposure_candidates, default=None)

    expired_legs = tuple(
        leg_id
        for leg_id in leg_values
        if clock_trusted
        and leg_origins.get(leg_id) is not None
        and now_upper_ns >= leg_origins[leg_id] + LEG_TTL_NS
    )
    aggregate_expired = bool(
        clock_trusted
        and exposure_origin is not None
        and now_upper_ns >= exposure_origin + UNHEDGED_TTL_NS
    )
    hold_expired = bool(
        clock_trusted
        and exposure_origin is not None
        and now_upper_ns >= exposure_origin + HOLDING_TTL_NS
    )
    # The documented 50ms cadence allows the equality boundary. It is a
    # cadence budget, not one of the 1/3/60-second fail-closed deadlines.
    idle_overdue = bool(
        clock_trusted
        and type(last_idle_lower_ns) is int
        and last_idle_lower_ns >= 0
        and now_upper_ns > last_idle_lower_ns + IDLE_INTERVAL_NS
    )
    confirmed = any(fact.fact_type in _CONFIRMATION_FACT_TYPES for fact in admissible)
    expired_reasons = tuple(
        reason
        for reason, expired in (
            ("PER_LEG_TTL_EXCEEDED", bool(expired_legs)),
            ("UNHEDGED_TTL_EXCEEDED", aggregate_expired),
            ("HOLDING_TTL_EXCEEDED", hold_expired),
            ("IDLE_INTERVAL_EXCEEDED", idle_overdue),
        )
        if expired
    )
    protection_required = bool(expired_reasons)

    if not clock_trusted:
        proposals = (_proposal("BLOCK", "TRUSTED_NOW_REQUIRED", exposure_origin, now_upper_ns),)
        status, reason = "BLOCKED_SOURCE", "TRUSTED_NOW_REQUIRED"
    elif expired_reasons:
        proposals = (
            _proposal("PROTECT", "+".join(expired_reasons), exposure_origin, now_upper_ns),
        )
        status, reason = "OFFLINE_SIGNAL_ONLY", "+".join(expired_reasons)
    else:
        proposals = (_proposal("OBSERVE", "NO_DEADLINE_EXCEEDED", exposure_origin, now_upper_ns),)
        status, reason = "OFFLINE_SIGNAL_ONLY", "NO_SCOPED_EXECUTION_FACTS"

    return TimingProjection(
        clock_trusted=clock_trusted,
        admissible_fact_ids=admissible_ids,
        uncertain_fact_ids=uncertain_ids,
        origin_lower_ns=per_leg_origin,
        confirmed=confirmed,
        per_leg_expired=expired_legs,
        aggregate_expired=aggregate_expired,
        hold_expired=hold_expired,
        idle_overdue=idle_overdue,
        expired_reasons=expired_reasons,
        protection_required=protection_required,
        native_write_eligible=False,
        proposals=proposals,
        exposure_origin_lower_ns=exposure_origin,
        status=status,
        reason=reason,
        risk_projection_available=False,
    )


class TimingProjector:
    """Stateful local read model that freezes conservative timing origins.

    It only classifies facts supplied by the caller's provider. A fact that is
    foreign, malformed, unassociated, duplicate-conflicting, or from a retired
    scope is quarantined; it cannot confirm a leg or extend a deadline.
    """

    def __init__(
        self,
        *,
        scope: TimingScope,
        associations: Iterable[OrderAssociation],
        leg_ids: Iterable[str],
        lots_per_leg: int = 1,
        history_capacity: int = 128,
    ) -> None:
        """Validate and freeze one scope, one intent, and one association per leg.

        Malformed legs, non-synthetic lot counts, and associations that do
        not share a single intent/decision/basket/cycle identity are
        rejected here rather than during projection.
        """
        if not isinstance(scope, TimingScope):
            raise TimingContractError("TimingProjector.scope must be a TimingScope")
        legs = tuple(str(leg) for leg in leg_ids)
        if not legs or len(set(legs)) != len(legs) or any(not _identity(leg) for leg in legs):
            raise TimingContractError(
                "TimingProjector leg_ids must be distinct non-empty identities"
            )
        if type(lots_per_leg) is not int or lots_per_leg <= 0:
            raise TimingContractError("TimingProjector lots_per_leg must be positive")
        if lots_per_leg != 1 and not scope.synthetic:
            raise TimingContractError(
                "non-production lot counts are only permitted for synthetic fixtures"
            )
        if type(history_capacity) is not int or history_capacity <= 0:
            raise TimingContractError("TimingProjector history_capacity must be positive")
        association_values = tuple(associations)
        if len(association_values) != len(legs) or any(
            not isinstance(item, OrderAssociation) for item in association_values
        ):
            raise TimingContractError("TimingProjector needs one OrderAssociation per leg")
        association_by_leg = {item.leg_id: item for item in association_values}
        if set(association_by_leg) != set(legs) or len(association_by_leg) != len(
            association_values
        ):
            raise TimingContractError("OrderAssociation legs must exactly match projector legs")
        if any(item.intent_id != association_values[0].intent_id for item in association_values):
            raise TimingContractError("all OrderAssociations must share one intent")
        if any(
            (item.decision_id, item.basket_id, item.cycle_id)
            != (
                association_values[0].decision_id,
                association_values[0].basket_id,
                association_values[0].cycle_id,
            )
            for item in association_values
        ):
            raise TimingContractError(
                "all OrderAssociations must share decision/basket/cycle identity"
            )
        self.scope = scope
        self.leg_ids = legs
        self.lots_per_leg = lots_per_leg
        self._associations = association_by_leg
        self._intent_id = association_values[0].intent_id
        self._leg_origins: dict[str, int] = {}
        self._exposure_origin: int | None = None
        self._confirmed_quantities: dict[str, int] = dict.fromkeys(legs, 0)
        # Retain exact payloads rather than evicting historical identities.
        # Once the bounded ledger saturates, the projection latches ordinary
        # permissions closed because it cannot safely prove replay identity.
        self._history_capacity = history_capacity
        self._history_exhausted = False
        self._fact_payloads: dict[str, TimingFact] = {}
        self._trade_payloads: dict[tuple[str, str, str, str], tuple[object, ...]] = {}
        self._last_now_upper_ns: int | None = None
        self._last_idle_upper_ns: int | None = None
        self._clock_fault_reason: str | None = None
        self._audit_fact_ids: list[str] = []
        self._audit_fact_id_set: set[str] = set()
        self._unresolved_exposure = False
        # This is deliberately narrower than ``_unresolved_exposure``.  A
        # legal local durable intent is still an unresolved lifecycle state,
        # but a foreign/unknown exposure must additionally latch ordinary
        # permissions closed until external reconciliation (not implemented
        # by this zero-write projection).
        self._untrusted_exposure = False

    def _record_audit_fact_id(self, fact_id: str) -> None:
        """Keep a bounded exact audit ledger and fail closed on saturation."""

        if not _identity(fact_id) or fact_id in self._audit_fact_id_set:
            return
        if len(self._audit_fact_ids) >= self._history_capacity:
            self._history_exhausted = True
            return
        self._audit_fact_ids.append(fact_id)
        self._audit_fact_id_set.add(fact_id)

    def _admit_fact(self, fact: TimingFact, *, now_upper_ns: int) -> tuple[bool, str]:
        if not _identity(fact.fact_id) or fact.fact_type not in _FACT_TYPES:
            return False, "FACT_TYPE_UNKNOWN"
        if fact.scope != self.scope:
            return False, "FACT_SCOPE_MISMATCH"
        if fact.synthetic != self.scope.synthetic:
            return False, "FACT_SYNTHETIC_MISMATCH"
        if (
            fact.provider_id != self.scope.provider_id
            or fact.source_id != self.scope.source_id
            or fact.scope_id != self.scope.scope_id
            or fact.clock_domain_id != self.scope.clock_domain_id
            or fact.intent_id != self._intent_id
        ):
            return False, "FACT_IDENTITY_MISMATCH"
        association = self._associations.get(fact.leg_id)
        if association is None or not association.matches(fact):
            return False, "FACT_ORDER_ASSOCIATION_MISMATCH"
        if not _identity(fact.direction) or not _identity(fact.offset):
            return False, "FACT_DIRECTION_OR_OFFSET_INVALID"
        if type(fact.origin_lower_ns) is not int or fact.origin_lower_ns <= 0:
            return False, "FACT_ORIGIN_INVALID"
        if (
            type(fact.origin_upper_ns) is not int
            or fact.origin_upper_ns < fact.origin_lower_ns
            or fact.origin_upper_ns > now_upper_ns
        ):
            return False, "FACT_TIME_BOUNDS_INVALID"
        if fact.origin_lower_ns > now_upper_ns:
            return False, "FACT_FROM_FUTURE"
        if (
            type(fact.received_ns) is not int
            or fact.received_ns < fact.origin_lower_ns
            or fact.received_ns > now_upper_ns
        ):
            return False, "FACT_RECEIPT_TIME_INVALID"
        if fact.fact_type in _CONFIRMATION_FACT_TYPES:
            if (
                not _identity(fact.trade_id)
                or not _identity(fact.exchange_id)
                or type(fact.quantity) is not int
                or fact.quantity <= 0
            ):
                return False, "CONFIRMATION_IDENTITY_OR_QUANTITY_INVALID"
            if fact.cumulative_quantity is not None and (
                type(fact.cumulative_quantity) is not int
                or fact.cumulative_quantity < fact.quantity
                or fact.cumulative_quantity <= 0
            ):
                return False, "CONFIRMATION_CUMULATIVE_INVALID"
        return True, ""

    def _clock_failure(self, snapshot: TimingSnapshot) -> str | None:
        clock = snapshot.clock
        if snapshot.scope != self.scope or clock.scope != self.scope:
            return "CLOCK_SCOPE_MISMATCH"
        if not clock.trusted:
            return "CLOCK_UNTRUSTED"
        if self._last_now_upper_ns is not None and clock.now_upper_ns < self._last_now_upper_ns:
            return "CLOCK_REGRESSION"
        return None

    def _remember_confirmation(self, fact: TimingFact) -> tuple[bool, str]:
        """Apply a legal trade once; conflicting duplicate payloads quarantine."""

        key = (
            self.scope.account_fingerprint,
            fact.exchange_id,
            self.scope.trading_day,
            fact.trade_id,
        )
        payload = (
            fact.intent_id,
            fact.leg_id,
            fact.order_id,
            fact.quantity,
            fact.cumulative_quantity,
            fact.origin_lower_ns,
            fact.direction,
            fact.offset,
        )
        previous = self._trade_payloads.get(key)
        if previous is not None:
            return (previous == payload), "" if previous == payload else "DUPLICATE_TRADE_CONFLICT"
        cumulative = fact.cumulative_quantity
        quantity = int(cumulative if cumulative is not None else fact.quantity)
        if quantity > self.lots_per_leg:
            return False, "CONFIRMATION_EXCEEDS_CONFIGURED_LOTS"
        previous_quantity = self._confirmed_quantities[fact.leg_id]
        if cumulative is None:
            next_quantity = previous_quantity + int(fact.quantity)
        else:
            next_quantity = max(previous_quantity, quantity)
        if next_quantity > self.lots_per_leg:
            return False, "CONFIRMATION_EXCEEDS_CONFIGURED_LOTS"
        self._trade_payloads[key] = payload
        self._confirmed_quantities[fact.leg_id] = next_quantity
        return True, ""

    def _freeze_origins(self, facts: Iterable[TimingFact]) -> None:
        by_leg: dict[str, list[TimingFact]] = {leg: [] for leg in self.leg_ids}
        exposure_candidates: list[int] = []
        for fact in facts:
            by_leg[fact.leg_id].append(fact)
            if fact.fact_type in _EXPOSURE_FACT_TYPES:
                exposure_candidates.append(fact.origin_lower_ns)

        for leg_id, leg_facts in by_leg.items():
            durable = [
                fact.origin_lower_ns for fact in leg_facts if fact.fact_type == "durable_intent"
            ]
            sends = [fact.origin_lower_ns for fact in leg_facts if fact.fact_type == "send"]
            # A send before its durable intent cannot be a causal native-send
            # proof. It remains audit evidence but cannot reset a deadline.
            causal_sends = [value for value in sends if not durable or value >= min(durable)]
            candidate = min(causal_sends) if causal_sends else min(durable, default=None)
            previous = self._leg_origins.get(leg_id)
            if candidate is not None and (previous is None or candidate < previous):
                self._leg_origins[leg_id] = candidate

        if exposure_candidates:
            candidate = min(exposure_candidates)
            if self._exposure_origin is None or candidate < self._exposure_origin:
                self._exposure_origin = candidate
        if self._exposure_origin is not None:
            self._unresolved_exposure = True

    def _quarantine(self, fact: TimingFact, quarantined: list[str]) -> None:
        """Retain an invalid fact for audit and latch any possible exposure.

        This helper is intentionally used before and after ``_admit_fact``:
        duplicate IDs and confirmation-ledger conflicts are rejected through
        separate paths, but neither may bypass the same conservative exposure
        treatment as a direct scope/time/association rejection.
        """

        quarantined.append(fact.fact_id)
        if fact.fact_type in _EXPOSURE_FACT_TYPES:
            self._unresolved_exposure = True
            self._untrusted_exposure = True

    @staticmethod
    def _calendar_status(snapshot: TimingSnapshot) -> tuple[str, bool, bool, bool]:
        seconds = snapshot.calendar_seconds_until_close
        if seconds is None:
            return "CALENDAR_REQUIRED", False, False, False
        if seconds <= 180:
            return "HANDOVER_IF_PENDING", False, True, True
        if seconds <= 600:
            return "RISK_EXIT", False, True, False
        if seconds <= 1800:
            return "STOP_ENTRY", False, False, False
        return "OPEN", True, False, False

    def _blocked_projection(
        self,
        *,
        reason: str,
        callback: str,
        quarantined: Iterable[str] = (),
        now_upper_ns: int | None = None,
    ) -> TimingProjection:
        origin = self._exposure_origin
        return TimingProjection(
            clock_trusted=False,
            admissible_fact_ids=(),
            uncertain_fact_ids=tuple(sorted(set(quarantined))),
            origin_lower_ns=min(self._leg_origins.values(), default=None),
            confirmed=any(self._confirmed_quantities.values()),
            per_leg_expired=(),
            aggregate_expired=False,
            hold_expired=False,
            idle_overdue=False,
            expired_reasons=(),
            protection_required=self._unresolved_exposure,
            native_write_eligible=False,
            proposals=(_proposal("BLOCK", reason, origin, now_upper_ns),),
            exposure_origin_lower_ns=origin,
            status="BLOCKED_SOURCE",
            reason=reason,
            callback=callback,
            risk_projection_available=False,
            ordinary_entry_allowed=False,
            confirmed_quantities=tuple(sorted(self._confirmed_quantities.items())),
            unresolved_exposure=self._unresolved_exposure,
            quarantined_fact_ids=tuple(sorted(set(quarantined))),
            audit_fact_ids=tuple(self._audit_fact_ids),
        )

    def project(self, snapshot: TimingSnapshot, *, callback: str) -> TimingProjection:
        """Classify one provider snapshot without a write or authorization."""

        if callback not in _CALLBACKS:
            raise TimingContractError("callback must be tick, next, bar, or idle")
        if not isinstance(snapshot, TimingSnapshot):
            raise TimingContractError("snapshot must be a TimingSnapshot")
        for fact in snapshot.facts:
            self._record_audit_fact_id(fact.fact_id)
        failure = self._clock_failure(snapshot)
        if failure is not None:
            self._clock_fault_reason = failure
            return self._blocked_projection(
                reason=failure,
                callback=callback,
                quarantined=(fact.fact_id for fact in snapshot.facts),
                now_upper_ns=snapshot.clock.now_upper_ns,
            )
        if self._clock_fault_reason is not None:
            return self._blocked_projection(
                reason=self._clock_fault_reason,
                callback=callback,
                quarantined=(fact.fact_id for fact in snapshot.facts),
                now_upper_ns=snapshot.clock.now_upper_ns,
            )

        admitted: list[TimingFact] = []
        quarantined: list[str] = []
        seen_facts: dict[str, TimingFact] = {}
        for fact in snapshot.facts:
            previous = seen_facts.get(fact.fact_id)
            if previous is not None:
                if previous != fact:
                    self._quarantine(fact, quarantined)
                continue
            seen_facts[fact.fact_id] = fact
            ok, _reason = self._admit_fact(fact, now_upper_ns=snapshot.clock.now_upper_ns)
            if not ok:
                # An untrusted foreign/unknown fact can never establish a
                # deadline or confirmation, but it still prevents a clean
                # flat conclusion while its possible exposure is audited. It
                # also must not coexist with an ordinary exit proposal: a
                # real reconciler is outside this local fixture path.
                self._quarantine(fact, quarantined)
                continue
            prior_payload = self._fact_payloads.get(fact.fact_id)
            if prior_payload is not None and prior_payload != fact:
                self._quarantine(fact, quarantined)
                continue
            if prior_payload is None:
                if len(self._fact_payloads) >= self._history_capacity:
                    self._history_exhausted = True
                    self._quarantine(fact, quarantined)
                    continue
                self._fact_payloads[fact.fact_id] = fact
            admitted.append(fact)

        for fact in admitted:
            if fact.fact_type not in _CONFIRMATION_FACT_TYPES:
                continue
            remembered, _reason = self._remember_confirmation(fact)
            if not remembered:
                self._quarantine(fact, quarantined)

        illegal_ids = set(quarantined)
        legal_facts = [fact for fact in admitted if fact.fact_id not in illegal_ids]
        self._freeze_origins(legal_facts)
        now_upper = snapshot.clock.now_upper_ns
        self._last_now_upper_ns = now_upper
        per_leg_expired = tuple(
            leg
            for leg in self.leg_ids
            if leg in self._leg_origins and now_upper >= self._leg_origins[leg] + LEG_TTL_NS
        )
        aggregate_expired = bool(
            self._exposure_origin is not None
            and now_upper >= self._exposure_origin + UNHEDGED_TTL_NS
        )
        hold_expired = bool(
            self._exposure_origin is not None
            and now_upper >= self._exposure_origin + HOLDING_TTL_NS
        )
        idle_overdue = bool(
            callback == "idle"
            and self._last_idle_upper_ns is not None
            and now_upper > self._last_idle_upper_ns + IDLE_INTERVAL_NS
        )
        if callback == "idle":
            self._last_idle_upper_ns = now_upper
        calendar_status, _entry_allowed, risk_exit_due, handover_due = self._calendar_status(
            snapshot
        )
        calendar_required = calendar_status == "CALENDAR_REQUIRED"
        expired_reasons = tuple(
            reason
            for reason, expired in (
                ("PER_LEG_TTL_EXCEEDED", bool(per_leg_expired)),
                ("UNHEDGED_TTL_EXCEEDED", aggregate_expired),
                ("HOLDING_TTL_EXCEEDED", hold_expired),
                ("IDLE_INTERVAL_EXCEEDED", idle_overdue),
                ("SESSION_RISK_EXIT_DUE", risk_exit_due),
                ("SESSION_HANDOVER_DUE", handover_due),
                ("STOP_REQUESTED", snapshot.stop_requested),
                ("CALENDAR_REQUIRED", calendar_required),
                ("HISTORY_CAPACITY_EXCEEDED", self._history_exhausted),
            )
            if expired
        )
        protection_required = bool(expired_reasons) or self._untrusted_exposure
        quantities = tuple(sorted(self._confirmed_quantities.items()))
        fully_confirmed = bool(quantities) and all(
            quantity == self.lots_per_leg for _, quantity in quantities
        )
        normal_exit_allowed = bool(
            callback == "tick"
            and snapshot.legal_executable_quote
            and self._exposure_origin is not None
            and fully_confirmed
            and not protection_required
        )

        if snapshot.stop_requested and self._unresolved_exposure:
            status, reason = "STOP_INCOMPLETE", "UNRESOLVED_EXPOSURE"
            proposals = (
                _proposal(
                    "PROTECT",
                    "STOP_INCOMPLETE/UNRESOLVED_EXPOSURE",
                    self._exposure_origin,
                    now_upper,
                ),
            )
        elif not legal_facts:
            status, reason = "BLOCKED_SOURCE", "NO_ADMISSIBLE_EXECUTION_FACTS"
            proposals = (_proposal("BLOCK", reason, self._exposure_origin, now_upper),)
        elif protection_required:
            protection_reason = "+".join(expired_reasons) or "UNTRUSTED_EXPOSURE"
            status, reason = "SYNTHETIC_RISK_PROJECTION", protection_reason
            proposals = (_proposal("PROTECT", reason, self._exposure_origin, now_upper),)
        elif normal_exit_allowed:
            status, reason = "SYNTHETIC_RISK_PROJECTION", "TICK_ONLY_NORMAL_EXIT_PROPOSAL"
            proposals = (
                _proposal("NORMAL_EXIT_PROPOSAL", reason, self._exposure_origin, now_upper),
            )
        else:
            status, reason = "SYNTHETIC_RISK_PROJECTION", "OBSERVE_ONLY"
            proposals = (_proposal("OBSERVE", reason, self._exposure_origin, now_upper),)

        return TimingProjection(
            clock_trusted=True,
            admissible_fact_ids=tuple(sorted(fact.fact_id for fact in legal_facts)),
            uncertain_fact_ids=tuple(sorted(set(quarantined))),
            origin_lower_ns=min(self._leg_origins.values(), default=None),
            confirmed=any(quantity > 0 for _, quantity in quantities),
            per_leg_expired=per_leg_expired,
            aggregate_expired=aggregate_expired,
            hold_expired=hold_expired,
            idle_overdue=idle_overdue,
            expired_reasons=expired_reasons,
            protection_required=protection_required,
            native_write_eligible=False,
            proposals=proposals,
            exposure_origin_lower_ns=self._exposure_origin,
            status=status,
            reason=reason,
            callback=callback,
            risk_projection_available=bool(legal_facts),
            ordinary_entry_allowed=False,
            normal_exit_allowed=normal_exit_allowed,
            confirmed_quantities=quantities,
            unresolved_exposure=self._unresolved_exposure,
            quarantined_fact_ids=tuple(sorted(set(quarantined))),
            audit_fact_ids=tuple(self._audit_fact_ids),
            calendar_status=calendar_status,
        )


class SyntheticTimingProvider:
    """Finite local-only provider used by tests and never by a network mode."""

    def __init__(
        self,
        *,
        projector: TimingProjector,
        snapshots: Mapping[str, Iterable[TimingSnapshot]],
    ) -> None:
        """Require a synthetic projector and one snapshot queue per callback.

        Every queue entry must be a typed TimingSnapshot sharing the
        projector's scope; unknown callbacks are rejected outright.
        """
        if not isinstance(projector, TimingProjector) or not projector.scope.synthetic:
            raise TimingContractError(
                "SyntheticTimingProvider requires a synthetic TimingProjector"
            )
        queues: dict[str, list[TimingSnapshot]] = {}
        for callback, values in snapshots.items():
            if callback not in _CALLBACKS:
                raise TimingContractError("SyntheticTimingProvider callback is unknown")
            queue = list(values)
            if any(
                not isinstance(item, TimingSnapshot) or item.scope != projector.scope
                for item in queue
            ):
                raise TimingContractError(
                    "SyntheticTimingProvider snapshots must share projector scope"
                )
            queues[callback] = queue
        self.projector = projector
        self._queues = queues
        self.calls: dict[str, int] = dict.fromkeys(_CALLBACKS, 0)

    def project(self, callback: str) -> TimingProjection | None:
        """Pop the next queued snapshot for a callback and project it, else None."""
        queue = self._queues.get(callback, [])
        if not queue:
            return None
        self.calls[callback] += 1
        return self.projector.project(queue.pop(0), callback=callback)


def projection_to_dict(projection: TimingProjection) -> dict[str, object]:
    """Serialize a projection without exposing a mutable execution handle."""

    return {
        "clock_trusted": projection.clock_trusted,
        "admissible_fact_ids": projection.admissible_fact_ids,
        "uncertain_fact_ids": projection.uncertain_fact_ids,
        "origin_lower_ns": projection.origin_lower_ns,
        "exposure_origin_lower_ns": projection.exposure_origin_lower_ns,
        "confirmed": projection.confirmed,
        "confirmed_quantities": projection.confirmed_quantities,
        "per_leg_expired": projection.per_leg_expired,
        "aggregate_expired": projection.aggregate_expired,
        "hold_expired": projection.hold_expired,
        "idle_overdue": projection.idle_overdue,
        "expired_reasons": projection.expired_reasons,
        "protection_required": projection.protection_required,
        "native_write_eligible": projection.native_write_eligible,
        "status": projection.status,
        "reason": projection.reason,
        "callback": projection.callback,
        "risk_projection_available": projection.risk_projection_available,
        "ordinary_entry_allowed": projection.ordinary_entry_allowed,
        "normal_exit_allowed": projection.normal_exit_allowed,
        "unresolved_exposure": projection.unresolved_exposure,
        "quarantined_fact_ids": projection.quarantined_fact_ids,
        "audit_fact_ids": projection.audit_fact_ids,
        "calendar_status": projection.calendar_status,
        "proposals": tuple(
            {
                "action": proposal.action,
                "reason": proposal.reason,
                "origin_lower_ns": proposal.origin_lower_ns,
                "now_upper_ns": proposal.now_upper_ns,
                "native_write_eligible": proposal.native_write_eligible,
            }
            for proposal in projection.proposals
        ),
    }
