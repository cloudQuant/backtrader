"""Read-only HF-T1 timing projection for the Iteration 25 example.

This module deliberately does not send, cancel, persist, or acknowledge an
order.  It projects conservative deadlines from one admissible fact set.  A
fact without the current provider/source/scope/clock identity, intent, or
order association is retained only as uncertain evidence.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

LEG_TTL_NS = 1_000_000_000
UNHEDGED_TTL_NS = 3_000_000_000
HOLDING_TTL_NS = 60_000_000_000
IDLE_INTERVAL_NS = 50_000_000

_FACT_TYPES = frozenset(
    {"durable_intent", "send", "ack", "confirmed", "per_leg", "aggregate", "hold"}
)


@dataclass(frozen=True)
class TimingFact:
    """A candidate-local, immutable observation used by the timing oracle."""

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


def _identity(value: str) -> bool:
    return isinstance(value, str) and bool(value.strip())


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


def _proposal(action: str, reason: str, origin: int | None, now: int | None) -> RiskActionProposal:
    return RiskActionProposal(
        action=action,
        reason=reason,
        origin_lower_ns=origin,
        now_upper_ns=now,
        native_write_eligible=False,
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
    """Project deadlines using only facts in the current identity scope.

    ``now_upper_ns >= origin_lower_ns + TTL`` is the expiry rule.  ACKs and
    other late observations are intentionally excluded from origin selection.
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
    leg_values = tuple(leg_ids)

    durable: dict[str, int] = {}
    sends: dict[str, int] = {}
    for fact in admissible:
        if fact.fact_type == "durable_intent":
            durable[fact.leg_id] = min(
                durable.get(fact.leg_id, fact.origin_lower_ns), fact.origin_lower_ns
            )
        elif fact.fact_type == "send":
            sends[fact.leg_id] = min(
                sends.get(fact.leg_id, fact.origin_lower_ns), fact.origin_lower_ns
            )
    leg_origins = {leg_id: sends.get(leg_id, durable.get(leg_id)) for leg_id in leg_values}
    origin_candidates = tuple(origin for origin in leg_origins.values() if origin is not None)
    origin_lower = min(origin_candidates) if origin_candidates else None

    expired_legs = tuple(
        leg_id
        for leg_id in leg_values
        if clock_trusted
        and leg_origins.get(leg_id) is not None
        and now_upper_ns >= leg_origins[leg_id] + LEG_TTL_NS
    )
    aggregate_expired = bool(
        clock_trusted
        and origin_lower is not None
        and now_upper_ns >= origin_lower + UNHEDGED_TTL_NS
    )
    hold_expired = bool(
        clock_trusted and origin_lower is not None and now_upper_ns >= origin_lower + HOLDING_TTL_NS
    )
    idle_overdue = bool(
        clock_trusted
        and type(last_idle_lower_ns) is int
        and last_idle_lower_ns > 0
        and now_upper_ns >= last_idle_lower_ns + IDLE_INTERVAL_NS
    )
    confirmed = any(fact.fact_type == "confirmed" for fact in admissible)
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
        proposals = (_proposal("BLOCK", "TRUSTED_NOW_REQUIRED", origin_lower, now_upper_ns),)
    elif expired_reasons:
        proposals = (_proposal("PROTECT", "+".join(expired_reasons), origin_lower, now_upper_ns),)
    else:
        proposals = (_proposal("OBSERVE", "NO_DEADLINE_EXCEEDED", origin_lower, now_upper_ns),)

    return TimingProjection(
        clock_trusted=clock_trusted,
        admissible_fact_ids=admissible_ids,
        uncertain_fact_ids=uncertain_ids,
        origin_lower_ns=origin_lower,
        confirmed=confirmed,
        per_leg_expired=expired_legs,
        aggregate_expired=aggregate_expired,
        hold_expired=hold_expired,
        idle_overdue=idle_overdue,
        expired_reasons=expired_reasons,
        protection_required=protection_required,
        native_write_eligible=False,
        proposals=proposals,
    )


def projection_to_dict(projection: TimingProjection) -> dict[str, object]:
    """Serialize a projection without exposing a mutable execution handle."""

    return {
        "clock_trusted": projection.clock_trusted,
        "admissible_fact_ids": projection.admissible_fact_ids,
        "uncertain_fact_ids": projection.uncertain_fact_ids,
        "origin_lower_ns": projection.origin_lower_ns,
        "confirmed": projection.confirmed,
        "per_leg_expired": projection.per_leg_expired,
        "aggregate_expired": projection.aggregate_expired,
        "hold_expired": projection.hold_expired,
        "idle_overdue": projection.idle_overdue,
        "expired_reasons": projection.expired_reasons,
        "protection_required": projection.protection_required,
        "native_write_eligible": projection.native_write_eligible,
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
