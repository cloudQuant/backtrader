"""Rollover plans, readiness facts, and their validation."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional, Tuple
from bt_api_py.futures_selection import (
    MainContractManifest,
    MainContractSelectionBlocked,
    ProductKey,
    RolloverBoundaryEvidence,
    TradingDayReference,
    canonical_selection_json_sha256 as _canonical_json_sha256,
    selection_product_key as _key_order,
    selection_utc_text as _utc_text,
    validate_aware_selection_datetime as _aware_datetime,
    validate_selection_identity_text as _identity_text,
)



@dataclass(frozen=True)
class MainContractBinding:
    product: ProductKey
    instrument_id: str


@dataclass(frozen=True)
class MainContractRolloverPlan:
    status: str
    current_manifest_sha256: str
    proposed_manifest_sha256: str
    prior_epoch_id: str
    next_epoch_id: str
    effective_at: datetime
    boundary: RolloverBoundaryEvidence
    effective_trading_days: Tuple[TradingDayReference, ...]
    old_mapping: Tuple[MainContractBinding, ...]
    new_mapping: Tuple[MainContractBinding, ...]
    changed_products: Tuple[ProductKey, ...]
    halt_new_entries_until_ready: bool
    preserve_old_instrument_event_routing: bool
    reset_all_cohort_state: bool
    rewarm_all_members: bool
    required_checks: Tuple[str, ...]

    def __post_init__(self) -> None:
        _aware_datetime(self.effective_at, "rollover effective_at")
        if not isinstance(self.boundary, RolloverBoundaryEvidence):
            raise ValueError("rollover boundary must be RolloverBoundaryEvidence")
        for name in (
            "effective_trading_days",
            "old_mapping",
            "new_mapping",
            "changed_products",
            "required_checks",
        ):
            object.__setattr__(self, name, tuple(getattr(self, name)))


@dataclass(frozen=True)
class RolloverReadiness:
    """Observed old-epoch and whole-cohort facts required to activate a roll."""

    old_orders_terminal: bool
    old_positions_flat: bool
    old_order_events_reconciled: bool
    old_state_reconciled: bool
    unknown_order_count: int
    old_instrument_event_routes_preserved: bool
    all_cohort_state_reset: bool
    all_members_rewarmed: bool

    def __post_init__(self) -> None:
        for name in (
            "old_orders_terminal",
            "old_positions_flat",
            "old_order_events_reconciled",
            "old_state_reconciled",
            "old_instrument_event_routes_preserved",
            "all_cohort_state_reset",
            "all_members_rewarmed",
        ):
            if type(getattr(self, name)) is not bool:
                raise ValueError("{} must be a bool".format(name))
        if type(self.unknown_order_count) is not int or self.unknown_order_count < 0:
            raise ValueError("unknown_order_count must be a non-negative int")


@dataclass(frozen=True)
class RolloverAuthorization:
    status: str
    activation_allowed: bool
    activation_required: bool
    blockers: Tuple[str, ...]
    epoch_id: str


_ROLLOVER_CHECKS = (
    "OLD_ORDERS_TERMINAL",
    "OLD_ORDER_EVENTS_RECONCILED",
    "OLD_POSITIONS_FLAT",
    "OLD_STATE_RECONCILED",
    "UNKNOWN_ORDERS_ZERO",
    "OLD_INSTRUMENT_EVENT_ROUTES_PRESERVED",
    "ALL_COHORT_STATE_RESET",
    "ALL_MEMBERS_REWARMED",
)


def plan_main_contract_rollover(
    current: MainContractManifest,
    proposed: MainContractManifest,
    *,
    current_epoch_id: str,
    boundary: RolloverBoundaryEvidence,
) -> MainContractRolloverPlan:
    """Describe, but do not execute, a complete mapping epoch switch."""

    if current.status != "READY" or proposed.status != "READY":
        raise MainContractSelectionBlocked("rollover requires two READY manifests")
    _identity_text(current_epoch_id, "current_epoch_id")
    if not isinstance(boundary, RolloverBoundaryEvidence):
        raise ValueError("boundary must be RolloverBoundaryEvidence")
    if current.policy != proposed.policy:
        raise ValueError("rollover cannot change the frozen selection policy")
    if proposed.decision_at.astimezone(timezone.utc) <= current.decision_at.astimezone(
        timezone.utc
    ):
        raise ValueError("proposed selection predates the active selection")
    if boundary.available_at.astimezone(timezone.utc) > proposed.decision_at.astimezone(
        timezone.utc
    ):
        raise ValueError("rollover boundary evidence was unavailable at selection time")
    if boundary.retrieved_at.astimezone(timezone.utc) > proposed.decision_at.astimezone(
        timezone.utc
    ):
        raise ValueError("rollover boundary evidence was retrieved after selection time")
    if boundary.effective_at.astimezone(timezone.utc) < proposed.decision_at.astimezone(
        timezone.utc
    ):
        raise ValueError("rollover boundary precedes its selection evidence")

    old_pairs = current.selected_mapping()
    new_pairs = proposed.selected_mapping()
    old_by_key = {_key_order(key): value for key, value in old_pairs}
    new_by_key = {_key_order(key): value for key, value in new_pairs}
    if set(old_by_key) != set(new_by_key):
        raise ValueError("rollover target product pool changed")
    proposed_trading_days = {
        item.exchange_id: item.current_trading_day for item in proposed.trading_days
    }
    boundary_trading_days = {item.exchange_id: item.trading_day for item in boundary.trading_days}
    if boundary_trading_days != proposed_trading_days:
        raise ValueError("rollover boundary does not match the proposed TradingDay set")
    changed = tuple(
        current_key
        for current_key, _instrument in old_pairs
        if old_by_key[_key_order(current_key)] != new_by_key[_key_order(current_key)]
    )
    changed_ids = {_key_order(item) for item in changed}
    old_mapping = tuple(MainContractBinding(key, instrument) for key, instrument in old_pairs)
    new_mapping = tuple(MainContractBinding(key, instrument) for key, instrument in new_pairs)
    if changed:
        next_epoch = _canonical_json_sha256(
            {
                "prior_epoch_id": current_epoch_id,
                "proposed_manifest_sha256": proposed.manifest_sha256,
                "effective_at": _utc_text(boundary.effective_at),
                "changed_products": [list(item) for item in sorted(changed_ids)],
            }
        )
        status = "PENDING_OLD_EPOCH_RECONCILIATION"
        halt = True
        reset = True
        required = _ROLLOVER_CHECKS
    else:
        next_epoch = current_epoch_id
        status = "NO_MAPPING_CHANGE"
        halt = False
        reset = False
        required = ()
    return MainContractRolloverPlan(
        status=status,
        current_manifest_sha256=current.manifest_sha256,
        proposed_manifest_sha256=proposed.manifest_sha256,
        prior_epoch_id=current_epoch_id,
        next_epoch_id=next_epoch,
        effective_at=boundary.effective_at,
        boundary=boundary,
        effective_trading_days=proposed.trading_days,
        old_mapping=old_mapping,
        new_mapping=new_mapping,
        changed_products=changed,
        halt_new_entries_until_ready=halt,
        preserve_old_instrument_event_routing=bool(changed),
        reset_all_cohort_state=reset,
        rewarm_all_members=reset,
        required_checks=required,
    )


def authorize_main_contract_rollover(
    plan: MainContractRolloverPlan,
    readiness: Optional[RolloverReadiness],
) -> RolloverAuthorization:
    """Evaluate old-epoch facts; this function never changes an active mapping."""

    if not plan.changed_products:
        return RolloverAuthorization(
            status="NO_MAPPING_CHANGE",
            activation_allowed=True,
            activation_required=False,
            blockers=(),
            epoch_id=plan.prior_epoch_id,
        )
    if readiness is None:
        return RolloverAuthorization(
            status="BLOCKED_OLD_EPOCH_NOT_RECONCILED",
            activation_allowed=False,
            activation_required=True,
            blockers=("ROLLOVER_READINESS_UNAVAILABLE",),
            epoch_id=plan.prior_epoch_id,
        )
    blockers = []
    if not readiness.old_orders_terminal:
        blockers.append("OLD_ORDERS_NOT_TERMINAL")
    if not readiness.old_order_events_reconciled:
        blockers.append("OLD_ORDER_EVENTS_NOT_RECONCILED")
    if not readiness.old_positions_flat:
        blockers.append("OLD_POSITIONS_NOT_FLAT")
    if not readiness.old_state_reconciled:
        blockers.append("OLD_STATE_NOT_RECONCILED")
    if readiness.unknown_order_count != 0:
        blockers.append("UNKNOWN_ORDERS_PRESENT")
    if not readiness.old_instrument_event_routes_preserved:
        blockers.append("OLD_INSTRUMENT_EVENT_ROUTES_NOT_PRESERVED")
    if not readiness.all_cohort_state_reset:
        blockers.append("COHORT_STATE_NOT_RESET")
    if not readiness.all_members_rewarmed:
        blockers.append("COHORT_REWARM_INCOMPLETE")
    if blockers:
        return RolloverAuthorization(
            status="BLOCKED_OLD_EPOCH_NOT_RECONCILED",
            activation_allowed=False,
            activation_required=True,
            blockers=tuple(blockers),
            epoch_id=plan.prior_epoch_id,
        )
    return RolloverAuthorization(
        status="ACTIVATION_CONDITIONS_MET",
        activation_allowed=True,
        activation_required=True,
        blockers=(),
        epoch_id=plan.next_epoch_id,
    )
