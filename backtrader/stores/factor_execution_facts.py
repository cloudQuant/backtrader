"""No-SDK-I/O projections of current RegisteredSim execution evidence.

The runner owns bounded SDK refreshes through
``refresh_factor_execution_queries``.  A Strategy decision path calls only
``project_factor_execution_facts``: it reads the Store's sealed query cache,
the last TickEvent consumed by that Store, public no-I/O Broker snapshots,
and the same-journal position book's bounded local projection.  That indexed
SQLite read is part of decision-path latency; the projection never calls an
SDK or provider query.  Missing, stale, unmatched, or future facts stay
unknown and carry blockers.  This module does not contain a policy budget,
grant write authority, adopt external positions, or provide a replay shim.
"""

from __future__ import annotations

import math
import hashlib
import json
import threading
import time
from collections import defaultdict
from collections.abc import Mapping
from dataclasses import dataclass, replace
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from typing import Any, List, Optional, Tuple

from .registered_sim import RegisteredSimStore

_BASE_FAMILIES = (
    "account_result",
    "orders_result",
    "trades_result",
    "instruments_result",
    # Positions are refreshed last so they are causally after the terminal
    # orders rows used by the coordinator's bounded reconciliation proof.
    "positions_result",
)
_REQUEST_TYPES = {
    "account_result": "account",
    "positions_result": "positions",
    "orders_result": "orders",
    "trades_result": "trades",
    "instruments_result": "instruments",
    "instrument_margin_rate_result": "margin_rate",
}
_MARGIN_FILTERS = ("HedgeFlag",)
_CAPITAL_BLOCKERS = frozenset(
    {
        "available_margin_unobserved",
        "used_margin_unobserved",
        "current_notional_unobserved",
        "current_worst_case_loss_unobserved",
        "open_order_risk_capacity_unobserved",
        "long_margin_per_hand_unobserved",
        "short_margin_per_hand_unobserved",
    }
)
_THREADING_EVENT_TYPE = type(threading.Event())


@dataclass(frozen=True)
class FactorExecutionTarget:
    """Configured target bound to the data object already owned by Broker."""

    target_id: str
    instrument: str
    exchange: str
    data: Any

    def __post_init__(self) -> None:
        for name in ("target_id", "instrument", "exchange"):
            value = getattr(self, name)
            if type(value) is not str or not value or value != value.strip():
                raise ValueError("{} must be exact non-empty text".format(name))
        if self.data is None:
            raise ValueError("data must be the bound Broker data object")


@dataclass(frozen=True)
class FactorExecutionQueryFact:
    """Copied public provenance for one actual SDK QueryResult projection."""

    family: str
    request_type: Optional[str]
    request_id: Optional[int]
    connection_generation: Optional[int]
    account_fingerprint: Optional[str]
    trading_day: Optional[str]
    started_at: Optional[datetime]
    completed_at: Optional[datetime]
    source_owned: bool
    query_complete: bool
    scope_complete: Optional[bool]
    row_count: Optional[int]
    target_id: Optional[str] = None


@dataclass(frozen=True)
class FactorExecutionQuerySetFacts:
    """One completed, unfiltered core-query refresh batch.

    The ordered request IDs bind a projection to one actual refresh result.
    A later partial core refresh changes a Store cache ID and therefore cannot
    be combined with the still-young members of an older set.
    """

    query_set_id: str
    account_fingerprint: str
    connection_generation: int
    trading_day: str
    started_at_utc: datetime
    completed_at_utc: datetime
    query_ids: Tuple[Tuple[str, int], ...]


@dataclass(frozen=True)
class FactorExecutionRefreshReceipt:
    """Finite record of runner-owned refresh work and its actual query IDs."""

    started_at: datetime
    completed_at: datetime
    requested_families: Tuple[str, ...]
    attempted_families: Tuple[str, ...]
    query_provenance: Tuple[FactorExecutionQueryFact, ...]
    blockers: Tuple[str, ...]
    deadline_reached: bool
    pending_families: Tuple[str, ...] = ()
    cancelled: bool = False
    query_set: Optional[FactorExecutionQuerySetFacts] = None


@dataclass(frozen=True)
class FactorExecutionAccountFacts:
    account_scope: str
    snapshot_id: str
    available_at: datetime
    route_permitted: Optional[bool]
    available_margin: Optional[Decimal]
    used_margin: Optional[Decimal]
    current_notional: Optional[Decimal]
    current_worst_case_loss: Optional[Decimal]
    account_fingerprint: Optional[str] = None
    connection_generation: Optional[int] = None
    trading_day: Optional[str] = None


@dataclass(frozen=True)
class FactorExecutionPositionFacts:
    target_id: Optional[str]
    instrument: str
    exchange: str
    quantity: Optional[Decimal]
    snapshot_id: str
    available_at: datetime
    owner_strategy_scope: Optional[str]
    owner_intent_id: Optional[str]
    average_price: Optional[Decimal]
    stop_price: Optional[Decimal]
    held_eligible_bars: Optional[int]
    long_quantity: Optional[Decimal]
    short_quantity: Optional[Decimal]
    # Keep the Broker's no-I/O cached projection separately from attributed
    # strategy quantity.  This is useful for terminal-order reconciliation
    # even when the position book has not yet proved ownership.
    broker_quantity: Optional[Decimal] = None
    # Durable fill attribution can diverge from the Broker projection after an
    # overfill or other typed reconciliation issue. Preserve it separately;
    # it is never a substitute for the Broker quantity used to cap reductions.
    attributed_signed_quantity: Optional[Decimal] = None
    opening_fee_total: Optional[Decimal] = None
    opening_fees_known: Optional[bool] = None
    # Exact CTP PositionDate rows are kept separately from this net/side
    # projection.  SHFE/INE close offsets must be backed by these source rows
    # and matching durable opening-fill evidence; callers must never split a
    # net position into today/history quantities themselves.
    dated_inventory_rows: Tuple["FactorExecutionDatedInventoryRow", ...] = ()
    # Preserve the exact Book result that contributed a position blocker so
    # cancellation can distinguish its active-order reservation from unrelated
    # position uncertainty.  These fields never make retirement or CLOSE ready.
    position_book_status: Optional[str] = None
    position_book_blocker_code: Optional[str] = None


@dataclass(frozen=True)
class FactorExecutionDatedInventoryRow:
    """Immutable source row for one CTP position date/hedge bucket.

    ``position`` is the provider's current quantity for the explicit
    PositionDate row. ``yd_position`` is retained as the provider's prior-day
    baseline and is never used to calculate a current HISTORY balance.
    ``observed_fields`` distinguishes an absent source member from a present
    but malformed value, while blockers explain why the row cannot authorize
    a dated close.
    """

    instrument: str
    exchange: str
    position_side: Optional[str]
    hedge_flag: Optional[str]
    position_date_code: Optional[str]
    position_date: Optional[str]
    trading_day: Optional[str]
    position: Optional[Decimal]
    today_position: Optional[Decimal]
    yd_position: Optional[Decimal]
    long_frozen: Optional[Decimal]
    short_frozen: Optional[Decimal]
    comb_long_frozen: Optional[Decimal]
    comb_short_frozen: Optional[Decimal]
    strike_frozen: Optional[Decimal]
    abandon_frozen: Optional[Decimal]
    long_frozen_amount: Optional[Decimal]
    short_frozen_amount: Optional[Decimal]
    frozen_margin: Optional[Decimal]
    frozen_cash: Optional[Decimal]
    frozen_commission: Optional[Decimal]
    strike_frozen_amount: Optional[Decimal]
    yd_strike_frozen: Optional[Decimal]
    observed_fields: Tuple[str, ...]
    source_row_id: Optional[str]
    query_set_id: Optional[str]
    snapshot_id: Optional[str]
    request_id: Optional[int]
    connection_generation: Optional[int]
    account_fingerprint: Optional[str]
    available_at: Optional[datetime]
    blockers: Tuple[str, ...] = ()


@dataclass(frozen=True)
class FactorExecutionDatedCloseLegFacts:
    """Book-proved SHFE/INE close bucket mapped to one explicit CTP offset."""

    target_id: str
    instrument: str
    exchange: str
    position_side: Optional[str]
    hedge_flag: Optional[str]
    position_date: Optional[str]
    offset_flag: Optional[str]
    offset: Optional[str]
    side: Optional[str]
    provider_quantity: Optional[Decimal]
    owned_quantity: Optional[Decimal]
    available_quantity: Optional[Decimal]
    owner_strategy_scope: Optional[str]
    owner_intent_id: Optional[str]
    query_set_id: Optional[str]
    account_fingerprint: Optional[str]
    connection_generation: Optional[int]
    trading_day: Optional[str]
    snapshot_id: Optional[str]
    available_at: Optional[datetime]
    source_row_ids: Tuple[str, ...]
    opening_execution_ids: Tuple[str, ...]
    close_execution_ids: Tuple[str, ...]
    lots: Tuple["FactorExecutionDatedCloseLotFacts", ...]
    inventory_rows: Tuple[FactorExecutionDatedInventoryRow, ...]
    ready: bool
    blockers: Tuple[str, ...] = ()


@dataclass(frozen=True)
class FactorExecutionDatedCloseLotFacts:
    """Copied opening-lot evidence behind a dated close bucket."""

    execution_id: Optional[str]
    intent_id: Optional[str]
    owner_intent_id: Optional[str]
    strategy_scope: Optional[str]
    trading_day: Optional[str]
    position_side: Optional[str]
    hedge_flag: Optional[str]
    opened_quantity: Optional[Decimal]
    closed_quantity: Optional[Decimal]
    remaining_quantity: Optional[Decimal]
    open_observation_id: Optional[str]
    open_snapshot_id: Optional[str]
    open_query_set_id: Optional[str]
    close_execution_ids: Tuple[str, ...]


@dataclass(frozen=True)
class FactorExecutionWorkingOrderFacts:
    target_id: Optional[str]
    instrument: str
    exchange: Optional[str]
    order_ref: str
    state: str
    side: Optional[str]
    position_effect: Optional[str]
    remaining_quantity: Optional[Decimal]
    owner_strategy_scope: Optional[str]
    owner_intent_id: Optional[str]
    execution_unknown: Optional[bool]
    cancel_pending: Optional[bool]
    broker_order_ref: Optional[int] = None
    order_sys_id: Optional[str] = None
    front_id: Optional[int] = None
    session_id: Optional[int] = None


@dataclass(frozen=True)
class FactorExecutionTerminalOrderFacts:
    """One terminal CTP order row observed in a complete query snapshot.

    ``observation_id`` is a stable query-row identity, not a provider callback
    event ID.  It is bound to the source request and the exact native order
    identity/status so a coordinator can persist which complete query supplied
    terminal evidence.
    """

    instrument: str
    exchange: str
    order_ref: str
    order_sys_id: Optional[str]
    terminal_status: str
    terminal_state: str
    observation_id: str
    evidence_kind: str
    snapshot_id: str
    request_id: int
    connection_generation: int
    account_fingerprint: str
    trading_day: str
    available_at: datetime
    # CTP terminal rows may omit these in older archives. Keep absence
    # explicit for compatibility; UNKNOWN recovery requires the matching
    # native session and exact zero-fill volume tuple before it can proceed.
    front_id: Optional[int] = None
    session_id: Optional[int] = None
    volume_total_original: Optional[Decimal] = None
    volume_traded: Optional[Decimal] = None
    volume_total: Optional[Decimal] = None


@dataclass(frozen=True)
class FactorExecutionTradeObservationFacts:
    """A confirmed trade row from a complete source-owned CTP query.

    The row records source-provided trade time and price/volume.  It does not
    supply fee or callback identity; ``fee`` is always ``None`` and the stable
    observation ID is explicitly a query-row identity.
    """

    trade_id: str
    order_ref: str
    order_sys_id: Optional[str]
    instrument: str
    exchange: str
    direction: str
    side: str
    offset: str
    position_effect: str
    volume: Decimal
    price: Decimal
    trade_date: str
    trade_time: str
    trade_time_utc: datetime
    fee: Optional[Decimal]
    observation_id: str
    evidence_kind: str
    snapshot_id: str
    request_id: int
    connection_generation: int
    account_fingerprint: str
    trading_day: str
    available_at: datetime
    # Exact CTP single-character codes are preserved for dated inventory
    # reconciliation.  Only HedgeFlag 1/2/3/5 and offsets 0/3/4 are
    # interpreted by the dated position book; all other observed codes remain
    # visible and fail closed there.
    hedge_flag: Optional[str] = None
    offset_flag: Optional[str] = None


@dataclass(frozen=True)
class FactorExecutionQuoteFacts:
    instrument: str
    exchange: str
    source: Optional[str]
    source_ref: Optional[str]
    metadata_snapshot_id: Optional[str]
    generation: Optional[int]
    sequence: Optional[int]
    trading_day: Optional[str]
    event_time: Optional[datetime]
    available_at: Optional[datetime]
    bid: Optional[Decimal]
    ask: Optional[Decimal]
    bid_size: Optional[Decimal]
    ask_size: Optional[Decimal]
    tick_size: Optional[Decimal]
    lower_limit: Optional[Decimal]
    upper_limit: Optional[Decimal]
    quality: str


@dataclass(frozen=True)
class FactorExecutionInstrumentFacts:
    target_id: str
    instrument: str
    exchange: str
    snapshot_id: Optional[str]
    available_at: Optional[datetime]
    trading_permitted: Optional[bool]
    multiplier: Optional[Decimal]
    long_margin_per_hand: Optional[Decimal]
    short_margin_per_hand: Optional[Decimal]
    tick_size: Optional[Decimal]
    lower_limit: Optional[Decimal]
    upper_limit: Optional[Decimal]
    stop_loss_ticks: Optional[int] = None
    max_hands: Optional[int] = None


@dataclass(frozen=True)
class FactorExecutionRouteFacts:
    """Readiness of one configured route for strategy planning.

    ``eligible`` is a source-backed planning/readiness fact, not an active
    native capability grant.  The current SDK grant is exposed separately by
    the ``capability_*`` fields and is checked again at the outbound boundary.
    """

    target_id: str
    instrument: str
    exchange: str
    route_name: Optional[str]
    eligible: Optional[bool]
    allow_writes: Optional[bool]
    frozen: Optional[bool]
    capability_observed: Optional[bool]
    capability_managed: Optional[bool]
    capability_armed: Optional[bool]
    capability_matches_route: Optional[bool]
    instrument_query_complete: Optional[bool]
    instrument_eligible: Optional[bool]
    unknown_order_count: Optional[int]
    dispatching_order_count: Optional[int]
    connection_generation: Optional[int]
    trading_day: Optional[str]
    reason_codes: Tuple[str, ...]
    sdk_frozen: Optional[bool] = None
    arm_template_configured: Optional[bool] = None
    arm_templates_configured: Optional[bool] = None
    arm_api_available: Optional[bool] = None
    current_session_account_fingerprint: Optional[str] = None
    current_session_connection_generation: Optional[int] = None
    current_session_trading_day: Optional[str] = None
    current_session_trading_ready: Optional[bool] = None
    arm_template_membership: Optional[bool] = None


@dataclass(frozen=True)
class FactorExecutionFacts:
    """One immutable, same-session projection of live execution evidence."""

    account_scope: str
    strategy_scope: str
    snapshot_id: Optional[str]
    available_at: Optional[datetime]
    account: Optional[FactorExecutionAccountFacts]
    positions: Tuple[FactorExecutionPositionFacts, ...]
    working_orders: Tuple[FactorExecutionWorkingOrderFacts, ...]
    terminal_orders: Tuple[FactorExecutionTerminalOrderFacts, ...]
    trade_observations: Tuple[FactorExecutionTradeObservationFacts, ...]
    quotes: Tuple[FactorExecutionQuoteFacts, ...]
    instruments: Tuple[FactorExecutionInstrumentFacts, ...]
    route_eligibilities: Tuple[FactorExecutionRouteFacts, ...]
    query_provenance: Tuple[FactorExecutionQueryFact, ...]
    blockers: Tuple[str, ...]
    diagnostics: Tuple[str, ...] = ()
    query_set_id: Optional[str] = None
    dated_close_legs: Tuple[FactorExecutionDatedCloseLegFacts, ...] = ()
    # Execution grants are narrower than the complete observed factor/risk
    # universe.  ``None`` preserves the historical all-targets behavior for
    # callers that construct this value directly.
    target_ids: Optional[Tuple[str, ...]] = None
    execution_target_ids: Optional[Tuple[str, ...]] = None

    def __post_init__(self) -> None:
        for name in ("target_ids", "execution_target_ids"):
            value = getattr(self, name)
            if value is not None and type(value) is not tuple:
                raise TypeError("{} must be an immutable tuple or None".format(name))
        if self.target_ids is not None and (
            not self.target_ids
            or any(
                type(target_id) is not str or not target_id or target_id != target_id.strip()
                for target_id in self.target_ids
            )
            or len(set(self.target_ids)) != len(self.target_ids)
        ):
            raise ValueError("target_ids must contain unique non-empty text")
        if self.execution_target_ids is not None:
            full_target_ids = set(
                self.target_ids
                if self.target_ids is not None
                else tuple(item.target_id for item in self.route_eligibilities)
            )
            if (
                not self.execution_target_ids
                or any(
                    type(target_id) is not str or not target_id or target_id != target_id.strip()
                    for target_id in self.execution_target_ids
                )
                or len(set(self.execution_target_ids)) != len(self.execution_target_ids)
                or not set(self.execution_target_ids).issubset(full_target_ids)
            ):
                raise ValueError("execution_target_ids must be a non-empty immutable target subset")

    @property
    def _full_target_ids(self) -> Tuple[str, ...]:
        if self.target_ids is not None:
            return self.target_ids
        return tuple(item.target_id for item in self.route_eligibilities)

    @property
    def _authorized_target_id_set(self) -> frozenset:
        if self.execution_target_ids is None:
            return frozenset(self._full_target_ids)
        return frozenset(self.execution_target_ids)

    def _position_for_target(self, target_id: str):
        matches = tuple(item for item in self.positions if item.target_id == target_id)
        return matches[0] if len(matches) == 1 else None

    def _passive_observation_flat_state(self, target_id: str) -> Optional[bool]:
        """Prove that an unarmed observation-only target has no exposure/order."""

        route = next(
            (item for item in self.route_eligibilities if item.target_id == target_id), None
        )
        if any(
            order.target_id == target_id
            or (
                route is not None
                and (order.instrument, order.exchange) == (route.instrument, route.exchange)
            )
            for order in self.working_orders
        ):
            return False
        position = self._position_for_target(target_id)
        if (
            position is None
            or self.snapshot_id is None
            or position.snapshot_id != self.snapshot_id
            or self.available_at is None
            or position.available_at != self.available_at
        ):
            return None
        if (
            position.quantity is None
            or position.broker_quantity is None
            or position.long_quantity is None
            or position.short_quantity is None
        ):
            return None
        if any(
            value != 0
            for value in (
                position.quantity,
                position.broker_quantity,
                position.long_quantity,
                position.short_quantity,
            )
        ):
            return False
        if position.position_book_status != "FLAT":
            return None
        for row in position.dated_inventory_rows:
            if row.position is None:
                return None
            if row.position != 0:
                return False
        instrument = next((item for item in self.instruments if item.target_id == target_id), None)
        instrument_queries = tuple(
            fact for fact in self.query_provenance if fact.family == "instruments_result"
        )
        if (
            instrument is None
            or instrument.snapshot_id != self.snapshot_id
            or _aware_utc(instrument.available_at) is None
            or instrument.trading_permitted is not True
            or instrument.multiplier is None
            or instrument.tick_size is None
            or instrument.lower_limit is None
            or instrument.upper_limit is None
            or len(instrument_queries) != 1
            or not _base_query_provenance_complete(self.query_provenance, self.available_at)
        ):
            return None
        if (
            route is None
            or (route.instrument, route.exchange) != (position.instrument, position.exchange)
            or (instrument.instrument, instrument.exchange) != (route.instrument, route.exchange)
        ):
            return None
        return True

    def _safe_missing_template_route(self, route: FactorExecutionRouteFacts) -> bool:
        """Allow only a same-snapshot, flat, unarmed rank-only route."""

        target_id = route.target_id
        account = self.account
        if (
            target_id in self._authorized_target_id_set
            or account is None
            or self.snapshot_id is None
            or self.query_set_id is None
            or self.available_at is None
            or account.snapshot_id != self.snapshot_id
            or account.available_at != self.available_at
            or account.account_fingerprint is None
            or account.connection_generation is None
            or account.trading_day is None
            or not _base_query_provenance_complete(self.query_provenance, self.available_at)
            or self._passive_observation_flat_state(target_id) is not True
        ):
            return False
        if (
            route.route_name != "ctp/direct/registered-sim"
            or route.allow_writes is not True
            or route.frozen is not False
            or route.sdk_frozen is not False
            or route.capability_observed is not True
            or route.instrument_query_complete is not True
            or route.instrument_eligible is not True
            or route.unknown_order_count != 0
            or route.dispatching_order_count != 0
            or route.connection_generation != account.connection_generation
            or route.trading_day != account.trading_day
            or route.current_session_account_fingerprint != account.account_fingerprint
            or route.current_session_connection_generation != account.connection_generation
            or route.current_session_trading_day != account.trading_day
            or route.current_session_trading_ready is not True
            or route.arm_templates_configured is not True
            or route.arm_template_membership is not False
            or route.arm_template_configured is True
            or route.arm_api_available is not True
            or route.eligible is not False
            or "query_snapshot_invalid_or_stale:instruments_result" in self.blockers
        ):
            return False
        permitted_route_blockers = {
            "route_ineligible:{}".format(target_id),
            "route_arm_template_missing:{}".format(target_id),
        }
        if any(
            blocker.startswith("route_")
            and blocker.endswith(":" + target_id)
            and blocker not in permitted_route_blockers
            for blocker in self.blockers
        ):
            return False
        return True

    def _has_canonical_missing_margin_snapshot(self, target_id: str) -> bool:
        """Return whether this target has exactly one canonical absent margin fact."""

        margin_facts = tuple(
            fact
            for fact in self.query_provenance
            if fact.family == "instrument_margin_rate_result" and fact.target_id == target_id
        )
        return bool(
            len(margin_facts) == 1
            and margin_facts[0] == _missing_query_fact("instrument_margin_rate_result", target_id)
        )

    @property
    def aggregate_write_blockers(self) -> Tuple[str, ...]:
        """Blockers for authorized writes, retaining the complete raw snapshot."""

        full_ids = self._full_target_ids
        authorized_ids = self._authorized_target_id_set
        blockers = list(self.blockers)
        if (
            not full_ids
            or len(set(full_ids)) != len(full_ids)
            or not authorized_ids
            or not authorized_ids.issubset(set(full_ids))
        ):
            blockers.append("execution_scope_target_set_invalid")
            return tuple(sorted(set(blockers)))

        for target_id in full_ids:
            if target_id in authorized_ids:
                continue
            state = self._passive_observation_flat_state(target_id)
            route = next(
                (item for item in self.route_eligibilities if item.target_id == target_id), None
            )
            if any(
                order.target_id == target_id
                or (
                    route is not None
                    and (order.instrument, order.exchange) == (route.instrument, route.exchange)
                )
                for order in self.working_orders
            ):
                blockers.append("execution_scope_observation_order_present:{}".format(target_id))
            elif state is None:
                blockers.append(
                    "execution_scope_observation_position_unavailable:{}".format(target_id)
                )
            elif state is False:
                blockers.append("execution_scope_observation_not_flat:{}".format(target_id))

        safe_missing_routes = {
            route.target_id
            for route in self.route_eligibilities
            if self._safe_missing_template_route(route)
        }
        if safe_missing_routes:
            # These two derived capital blockers apply only to opening risk.
            # A proven passive route needs no per-hand opening margin, while
            # the original blockers remain available on ``self.blockers``.
            safe_missing_margin_blockers = {
                blocker
                for target_id in safe_missing_routes
                for blocker in (
                    "long_margin_per_hand_unobserved:{}".format(target_id),
                    "short_margin_per_hand_unobserved:{}".format(target_id),
                )
            }
            safe_missing_margin_snapshot_blockers = {
                "query_failed:instrument_margin_rate_result:{}:unavailable".format(target_id)
                for target_id in safe_missing_routes
                if self._has_canonical_missing_margin_snapshot(target_id)
            }
            blockers = [
                blocker
                for blocker in blockers
                if blocker not in safe_missing_margin_blockers
                and blocker not in safe_missing_margin_snapshot_blockers
                and not any(
                    blocker == "route_ineligible:{}".format(target_id)
                    or blocker == "route_arm_template_missing:{}".format(target_id)
                    for target_id in safe_missing_routes
                )
            ]
        return tuple(sorted(set(blockers)))

    def _scoped_route_permitted(self) -> Optional[bool]:
        full_ids = self._full_target_ids
        authorized_ids = self._authorized_target_id_set
        if (
            not full_ids
            or len(set(full_ids)) != len(full_ids)
            or not authorized_ids
            or not authorized_ids.issubset(set(full_ids))
        ):
            return None
        routes = tuple(self.route_eligibilities)
        route_by_id = {item.target_id: item for item in routes}
        if len(route_by_id) != len(routes) or set(route_by_id) != set(full_ids):
            return None
        position_ids = tuple(item.target_id for item in self.positions)
        instrument_ids = tuple(item.target_id for item in self.instruments)
        if (
            any(target_id is None for target_id in position_ids)
            or len(set(position_ids)) != len(position_ids)
            or set(position_ids) != set(full_ids)
            or len(set(instrument_ids)) != len(instrument_ids)
            or set(instrument_ids) != set(full_ids)
        ):
            return None
        unknown = False
        for target_id in full_ids:
            route = route_by_id[target_id]
            if target_id in authorized_ids:
                if route.eligible is False:
                    return False
                if route.eligible is not True:
                    unknown = True
                continue
            passive_flat = self._passive_observation_flat_state(target_id)
            if passive_flat is False:
                return False
            if passive_flat is not True:
                unknown = True
                continue
            if route.eligible is True:
                continue
            if self._safe_missing_template_route(route):
                continue
            if route.eligible is False:
                return False
            unknown = True
        return None if unknown else True

    @property
    def dated_inventory_rows(self) -> Tuple[FactorExecutionDatedInventoryRow, ...]:
        """Flatten the exact per-target CTP dated inventory source rows."""

        return tuple(row for position in self.positions for row in position.dated_inventory_rows)

    @property
    def read_only_reconciliation_blockers(self) -> Tuple[str, ...]:
        """Return blockers for retiring a run from a read-only snapshot.

        This is not order or risk permission. It proves only that the current
        query/session, position, and order/trade projections are coherent; the
        Strategy must still require its own flat-position and no-owned-order
        conditions before retirement. Write permission, an arm template or
        active grant, quotes, and capital inputs are deliberately irrelevant.
        """

        return _read_only_reconciliation_blockers(self)

    @property
    def read_only_reconciliation_ready(self) -> bool:
        """Whether this immutable projection is complete for read-only retirement."""

        return not self.read_only_reconciliation_blockers

    @property
    def read_only_observation_blockers(self) -> Tuple[str, ...]:
        """Return evidence gaps that prevent passive observation from ending.

        Unlike ``read_only_reconciliation_blockers``, this projection does not
        require current positions or working orders to be attributed to this
        Strategy or joined to its local Broker. It still requires complete,
        fresh, same-session query facts and a fully typed current remote order
        state. Callers must separately prove that the session is configured
        read-only before using this property to retire an observation run.
        """

        return _read_only_reconciliation_blockers(self, allow_unowned_state=True)

    @property
    def read_only_observation_ready(self) -> bool:
        """Whether complete current facts support ending observation only."""

        return not self.read_only_observation_blockers

    @property
    def risk_reduction_blockers(self) -> Tuple[str, ...]:
        """Blockers that prevent safely evaluating exits or reducing exposure.

        Missing account capacity and opening-margin facts are reported in
        ``blockers`` but do not by themselves prevent a fully evidenced close.
        This property is a deterministic classification of facts, never an
        authorization or an override for the Strategy's configured policy.
        """

        return tuple(
            code
            for code in self.aggregate_write_blockers
            if not _is_capital_blocker(code) and not _is_open_risk_only_blocker(code)
        )

    @property
    def risk_reduction_ready(self) -> bool:
        return bool(
            self.snapshot_id is not None
            and self.available_at is not None
            and self.account is not None
            and self.account.route_permitted is True
            and self._scoped_route_permitted() is True
            and _base_query_provenance_complete(self.query_provenance, self.available_at)
            and not self.risk_reduction_blockers
            and self.positions
            and all(item.quantity is not None for item in self.positions)
            and all(
                item.broker_quantity is not None
                and item.quantity == item.broker_quantity
                and item.long_quantity is not None
                and item.short_quantity is not None
                for item in self.positions
            )
            and not any(item.target_id is None for item in self.positions)
            and all(
                item.quantity == 0
                or (
                    item.owner_strategy_scope == self.strategy_scope
                    and item.owner_intent_id is not None
                )
                for item in self.positions
            )
            and all(item.quality == "GOOD" for item in self.quotes)
            and len(self.quotes) == len(self.instruments) == len(self.positions)
            and all(
                item.trading_permitted is True
                and item.multiplier is not None
                and item.tick_size is not None
                and item.lower_limit is not None
                and item.upper_limit is not None
                for item in self.instruments
            )
            and all(item.target_id is not None for item in self.route_eligibilities)
            and len(self.route_eligibilities) == len(self.positions)
            and _dated_close_positions_ready(self)
        )

    @property
    def open_risk_ready(self) -> bool:
        """True only when the live state is complete for a new-risk decision."""

        authorized_ids = self._authorized_target_id_set
        authorized_instruments = tuple(
            item for item in self.instruments if item.target_id in authorized_ids
        )
        return bool(
            self.risk_reduction_ready
            and not self.aggregate_write_blockers
            and self.account is not None
            and self.account.available_margin is not None
            and self.account.used_margin is not None
            and self.account.current_notional is not None
            and self.account.current_worst_case_loss is not None
            and len(authorized_instruments) == len(authorized_ids)
            and all(
                item.multiplier is not None
                and item.long_margin_per_hand is not None
                and item.short_margin_per_hand is not None
                for item in authorized_instruments
            )
        )

    @property
    def order_cancel_blockers(self) -> Tuple[str, ...]:
        """Facts blockers relevant to cancelling a positively joined order.

        Quote, position attribution, hold age and capital projections do not
        prove or disprove the remote/local order identity. Existing
        position-only blocker classification is preserved. The Book's bare
        ``INSTRUMENT_ORDER_UNRESOLVED`` reservation is ignored only when every
        affected target has a complete, owned Broker/CTP order join in this
        same projection. A derived unavailable dated-close blocker is ignored
        only for one matching owned CLOSE leg; multiple dated buckets remain
        ambiguous because the working-order facts do not carry a close offset.
        """

        ignored_prefixes = (
            "consumed_quote_",
            "consumed_stream_",
            "position_",
            "position_book_",
            "broker_position_",
        )
        exact_join = _exact_owned_cancel_join_covers_book_blocker(self)
        ignored_dated_close_blockers = set()
        if exact_join:
            unavailable_legs_by_target = {}
            for leg in self.dated_close_legs:
                if leg.ready:
                    continue
                blocker = "dated_close_leg_unavailable:{}:{}:{}:{}".format(
                    leg.target_id,
                    leg.position_side or "unknown",
                    leg.hedge_flag or "unknown",
                    leg.position_date or "unknown",
                )
                if blocker not in self.blockers:
                    continue
                unavailable_legs_by_target.setdefault(leg.target_id, []).append((leg, blocker))
            for target_legs in unavailable_legs_by_target.values():
                # The current working-order projection does not carry a close
                # offset. If multiple dated buckets share a target, do not
                # guess which bucket the CTP order can reduce.
                if len(target_legs) != 1:
                    continue
                leg, blocker = target_legs[0]
                position = self._position_for_target(leg.target_id)
                order_side = {"LONG": "SELL", "SHORT": "BUY"}.get(leg.position_side)
                if (
                    position is None
                    or (leg.instrument, leg.exchange) != (position.instrument, position.exchange)
                    or order_side is None
                    or leg.side != order_side
                    or "DATED_TARGET_HAS_WORKING_ORDER" not in leg.blockers
                ):
                    continue
                matching_orders = tuple(
                    order
                    for order in self.working_orders
                    if order.target_id == leg.target_id
                    and order.instrument == leg.instrument
                    and order.exchange == leg.exchange
                    and order.position_effect == "CLOSE"
                    and order.side == order_side
                )
                if len(matching_orders) == 1:
                    ignored_dated_close_blockers.add(blocker)
        return tuple(
            code
            for code in self.aggregate_write_blockers
            if not _is_capital_blocker(code)
            and not _is_open_risk_only_blocker(code)
            and not code.startswith(ignored_prefixes)
            and code not in ignored_dated_close_blockers
            and not (code == "INSTRUMENT_ORDER_UNRESOLVED" and exact_join)
        )

    @property
    def order_cancel_ready(self) -> bool:
        """Whether exact owned active orders can be cancelled without a quote."""

        routes_by_target = {item.target_id: item for item in self.route_eligibilities}
        return bool(
            self.snapshot_id is not None
            and self.query_set_id is not None
            and self.available_at is not None
            and self.account is not None
            and self.account.route_permitted is True
            and self._scoped_route_permitted() is True
            and _base_query_provenance_complete(self.query_provenance, self.available_at)
            and not self.order_cancel_blockers
            and self.working_orders
            and all(
                item.target_id in self._authorized_target_id_set for item in self.working_orders
            )
            and all(
                item.target_id is not None
                and item.instrument
                and item.exchange
                and item.order_ref
                and item.state in {"ACCEPTED", "PARTIAL"}
                and item.side in {"BUY", "SELL"}
                and item.position_effect in {"OPEN", "CLOSE"}
                and item.remaining_quantity is not None
                and item.remaining_quantity > 0
                and item.owner_strategy_scope == self.strategy_scope
                and item.owner_intent_id is not None
                and item.execution_unknown is False
                and item.cancel_pending is False
                and type(item.broker_order_ref) is int
                and item.broker_order_ref > 0
                and type(item.front_id) is int
                and item.front_id > 0
                and type(item.session_id) is int
                and item.session_id > 0
                for item in self.working_orders
            )
            and self.route_eligibilities
            and all(
                routes_by_target.get(item.target_id) is not None
                and routes_by_target[item.target_id].eligible is True
                for item in self.working_orders
            )
            and len(self.route_eligibilities) == len(self.positions)
        )


def _read_only_reconciliation_blockers(
    facts: FactorExecutionFacts, *, allow_unowned_state: bool = False
) -> Tuple[str, ...]:
    """Validate source identity and projections without requiring write facts."""

    blockers = set()

    def block(code: str) -> None:
        blockers.add(code)

    if (
        type(facts.account_scope) is not str
        or not facts.account_scope
        or facts.account_scope != facts.account_scope.strip()
    ):
        block("read_only_account_scope_unobserved")
    if (
        type(facts.strategy_scope) is not str
        or not facts.strategy_scope
        or facts.strategy_scope != facts.strategy_scope.strip()
    ):
        block("read_only_strategy_scope_unobserved")
    if (
        _exact_text(facts.snapshot_id) is None
        or _exact_text(facts.query_set_id) is None
        or _aware_utc(facts.available_at) is None
    ):
        block("read_only_snapshot_binding_unobserved")

    account = facts.account
    if account is None:
        block("read_only_account_projection_unavailable")
    elif (
        account.account_scope != facts.account_scope
        or account.snapshot_id != facts.snapshot_id
        or _aware_utc(account.available_at) != _aware_utc(facts.available_at)
    ):
        block("read_only_account_binding_mismatch")

    provenance = tuple(facts.query_provenance)
    available_at = _aware_utc(facts.available_at)
    if available_at is None or not _base_query_provenance_complete(provenance, available_at):
        block("read_only_core_query_provenance_incomplete")
    else:
        base = tuple(fact for fact in provenance if fact.family in _BASE_FAMILIES)
        by_family = {fact.family: fact for fact in base}
        if len(by_family) != len(_BASE_FAMILIES):
            block("read_only_core_query_identity_ambiguous")
        else:
            ordered = tuple(by_family[family] for family in _BASE_FAMILIES)
            generation = ordered[0].connection_generation
            trading_day = ordered[0].trading_day
            account_fingerprint = ordered[0].account_fingerprint
            query_ids = tuple((family, by_family[family].request_id) for family in _BASE_FAMILIES)
            starts = tuple(fact.started_at for fact in ordered)
            completions = tuple(fact.completed_at for fact in ordered)
            if (
                any(value is None for value in starts + completions)
                or account is None
                or generation is None
                or trading_day is None
                or account_fingerprint is None
                or len(set(query_ids)) != len(_BASE_FAMILIES)
                or account.connection_generation != generation
                or account.trading_day != trading_day
                or account.account_fingerprint != account_fingerprint
                or available_at != max(completions)
                or facts.query_set_id
                != _query_set_identifier(
                    account_fingerprint,
                    generation,
                    trading_day,
                    min(starts),
                    max(completions),
                    query_ids,
                )
            ):
                block("read_only_core_query_identity_mismatch")

    positions = tuple(facts.positions)
    routes = tuple(facts.route_eligibilities)
    instruments = tuple(facts.instruments)
    if not positions:
        block("read_only_target_positions_unobserved")

    external_positions = ()
    target_positions = positions
    external_position_blockers = set()
    valid_foreign_target_ids = set()
    configured_routes = {
        (instrument, exchange)
        for route in routes
        if (instrument := _exact_text(route.instrument)) is not None
        and (exchange := _exact_text(route.exchange)) is not None
    }
    if allow_unowned_state:
        # The account-wide CTP position query may include other instruments
        # outside this Strategy's exact target universe. Preserve those rows
        # only when their source-bound position projection is complete.
        external_positions = tuple(
            position for position in positions if position.target_id is None
        )
        target_positions = tuple(
            position for position in positions if position.target_id is not None
        )
        external_routes = set()
        for position in external_positions:
            instrument = _exact_text(position.instrument)
            exchange = _exact_text(position.exchange)
            quantity = position.quantity
            long_quantity = position.long_quantity
            short_quantity = position.short_quantity
            row_valid = (
                instrument is not None
                and exchange is not None
                and isinstance(quantity, Decimal)
                and quantity.is_finite()
                and quantity != 0
                and isinstance(long_quantity, Decimal)
                and long_quantity.is_finite()
                and long_quantity >= 0
                and isinstance(short_quantity, Decimal)
                and short_quantity.is_finite()
                and short_quantity >= 0
                and not (long_quantity and short_quantity)
                and quantity == long_quantity - short_quantity
                and (instrument, exchange) not in configured_routes
                and position.broker_quantity is None
                and position.owner_strategy_scope is None
                and position.owner_intent_id is None
                and position.average_price is None
                and position.stop_price is None
                and position.held_eligible_bars is None
                and position.attributed_signed_quantity is None
                and position.opening_fee_total is None
                and position.opening_fees_known is None
                and position.snapshot_id == facts.snapshot_id
                and _aware_utc(position.available_at) == available_at
            )
            route = (instrument, exchange)
            if route in external_routes:
                row_valid = False
            external_routes.add(route)
            if row_valid:
                external_position_blockers.add(
                    "external_position_outside_target_scope:{}:{}".format(instrument, exchange)
                )
            else:
                block(
                    "read_only_external_position_projection_invalid:{}:{}".format(
                        instrument or "unknown", exchange or "unknown"
                    )
                )

        # The position book can positively identify a target holding owned by
        # another Strategy. Its public snapshot intentionally omits the other
        # owner's identity: this observation never grants attribution or write
        # authority. Accept only the exact status/code pair after its bound
        # Broker/CTP quantity and snapshot checks; UNKNOWN and mismatch states
        # continue to block passive retirement.
        for position in target_positions:
            target_id = _exact_text(position.target_id)
            if position.position_book_status != "FOREIGN_OWNER":
                continue
            quantity = position.quantity
            long_quantity = position.long_quantity
            short_quantity = position.short_quantity
            broker_quantity = position.broker_quantity
            if (
                target_id is not None
                and position.position_book_blocker_code == "POSITION_OWNED_BY_OTHER_STRATEGY"
                and isinstance(quantity, Decimal)
                and quantity.is_finite()
                and quantity != 0
                and isinstance(long_quantity, Decimal)
                and long_quantity.is_finite()
                and long_quantity >= 0
                and isinstance(short_quantity, Decimal)
                and short_quantity.is_finite()
                and short_quantity >= 0
                and not (long_quantity and short_quantity)
                and quantity == long_quantity - short_quantity
                and isinstance(broker_quantity, Decimal)
                and broker_quantity.is_finite()
                and broker_quantity == quantity
                and position.owner_strategy_scope is None
                and position.owner_intent_id is None
                and position.average_price is None
                and position.stop_price is None
                and position.held_eligible_bars is None
                and position.attributed_signed_quantity is None
                and position.opening_fee_total is None
                and position.opening_fees_known is False
                and position.snapshot_id == facts.snapshot_id
                and _aware_utc(position.available_at) == available_at
            ):
                valid_foreign_target_ids.add(target_id)
            else:
                block(
                    "read_only_foreign_position_projection_invalid:{}".format(
                        target_id or "unknown"
                    )
                )

    def target_keys(items: Tuple[Any, ...], label: str) -> set:
        keys = []
        for item in items:
            target_id = _exact_text(_field(item, "target_id"))
            instrument = _exact_text(_field(item, "instrument"))
            exchange = _exact_text(_field(item, "exchange"))
            if target_id is None or instrument is None or exchange is None:
                block("read_only_{}_identity_unobserved".format(label))
                continue
            keys.append((target_id, instrument, exchange))
        if len(set(keys)) != len(keys):
            block("read_only_{}_identity_duplicate".format(label))
        return set(keys)

    position_keys = target_keys(target_positions, "position")
    target_routes = {(instrument, exchange) for _target, instrument, exchange in position_keys}
    route_keys = target_keys(routes, "route")
    instrument_keys = target_keys(instruments, "instrument")
    if not routes or route_keys != position_keys:
        block("read_only_target_route_set_mismatch")
    if not instruments or instrument_keys != position_keys:
        block("read_only_target_instrument_set_mismatch")

    expected_identity = None
    if account is not None:
        expected_identity = (
            account.account_fingerprint,
            account.connection_generation,
            account.trading_day,
        )
    for route in routes:
        route_target = _exact_text(route.target_id)
        identity = expected_identity
        if (
            route.route_name != "ctp/direct/registered-sim"
            or _exact_text(route.instrument) is None
            or _exact_text(route.exchange) is None
        ):
            block("read_only_route_identity_invalid:{}".format(route_target or "unknown"))
        if (
            identity is None
            or route.connection_generation != identity[1]
            or route.trading_day != identity[2]
            or route.current_session_account_fingerprint != identity[0]
            or route.current_session_connection_generation != identity[1]
            or route.current_session_trading_day != identity[2]
        ):
            block("read_only_route_session_mismatch:{}".format(route_target or "unknown"))
        if route.frozen is not False or route.sdk_frozen is not False:
            block("read_only_route_frozen_or_unobserved:{}".format(route_target or "unknown"))
        if route.capability_observed is not True:
            block("read_only_route_state_unobserved:{}".format(route_target or "unknown"))
        if route.unknown_order_count != 0 or type(route.unknown_order_count) is not int:
            block(
                "read_only_unknown_orders_present_or_unobserved:{}".format(
                    route_target or "unknown"
                )
            )
        if route.dispatching_order_count != 0 or type(route.dispatching_order_count) is not int:
            block(
                "read_only_dispatch_state_present_or_unobserved:{}".format(
                    route_target or "unknown"
                )
            )
        if route.instrument_query_complete is not True:
            block("read_only_instrument_query_incomplete:{}".format(route_target or "unknown"))

    for position in positions:
        target_id = _exact_text(position.target_id)
        prefix = target_id or "unknown"
        quantity = position.quantity
        broker_quantity_matches = (
            position.broker_quantity is None
            if allow_unowned_state and position.target_id is None
            else position.broker_quantity == quantity
        )
        if (
            position.snapshot_id != facts.snapshot_id
            or _aware_utc(position.available_at) != available_at
            or not isinstance(quantity, Decimal)
            or not quantity.is_finite()
            or not broker_quantity_matches
            or not isinstance(position.long_quantity, Decimal)
            or not isinstance(position.short_quantity, Decimal)
            or not position.long_quantity.is_finite()
            or not position.short_quantity.is_finite()
            or position.long_quantity < 0
            or position.short_quantity < 0
            or quantity != position.long_quantity - position.short_quantity
            or (position.long_quantity != 0 and position.short_quantity != 0)
        ):
            block("read_only_position_projection_mismatch:{}".format(prefix))
        if not allow_unowned_state and quantity not in (None, Decimal(0)) and (
            position.owner_strategy_scope != facts.strategy_scope
            or _exact_text(position.owner_intent_id) is None
        ):
            block("read_only_position_owner_unresolved:{}".format(prefix))
        exchange = _exact_text(position.exchange)
        if exchange is not None and exchange.upper() in {"SHFE", "INE"}:
            for row in position.dated_inventory_rows:
                if (
                    row.blockers
                    or row.instrument != position.instrument
                    or row.exchange != position.exchange
                    or row.query_set_id != facts.query_set_id
                    or row.snapshot_id != facts.snapshot_id
                    or expected_identity is None
                    or row.connection_generation != expected_identity[1]
                    or row.account_fingerprint != expected_identity[0]
                    or row.trading_day != expected_identity[2]
                    or row.available_at is None
                    or row.position is None
                ):
                    block("read_only_dated_position_row_invalid:{}".format(prefix))

    for instrument in instruments:
        if instrument.snapshot_id != facts.snapshot_id:
            block("read_only_instrument_snapshot_mismatch:{}".format(instrument.target_id))

    observed_order_keys = set()
    observed_orders_by_target = {}
    for order in facts.working_orders:
        target_id = _exact_text(order.target_id)
        instrument = _exact_text(order.instrument)
        exchange = _exact_text(order.exchange)
        is_external_route = bool(
            allow_unowned_state
            and target_id is None
            and order.target_id is None
            and instrument is not None
            and exchange is not None
            and (instrument, exchange) not in target_routes
        )
        if allow_unowned_state:
            target_route_invalid = (
                not is_external_route
                if target_id is None
                else (target_id, instrument, exchange) not in position_keys
            )
        else:
            target_route_invalid = (
                target_id is None
                or (target_id, instrument, exchange) not in position_keys
            )
        order_ref = _exact_text(order.order_ref)
        state = _exact_text(order.state)
        side = _exact_text(order.side)
        position_effect = _exact_text(order.position_effect)
        order_key = (target_id, order_ref, instrument, exchange)
        common_invalid = (
            target_route_invalid
            or instrument is None
            or exchange is None
            or order_ref is None
            or order.order_ref != order_ref
            or side not in {"BUY", "SELL"}
            or position_effect not in {"OPEN", "CLOSE"}
            or not isinstance(order.remaining_quantity, Decimal)
            or not order.remaining_quantity.is_finite()
            or order.remaining_quantity <= 0
            or type(order.front_id) is not int
            or order.front_id <= 0
            or type(order.session_id) is not int
            or order.session_id <= 0
        )
        if allow_unowned_state:
            # A complete current orders query may report an active remote
            # order that is not joined to this process's Broker/order book.
            # Preserve it as observed state; do not convert that observation
            # into cancel/close authority or an endless retirement blocker.
            known_remote_only = (
                state == "REMOTE_ONLY"
                and order.broker_order_ref is None
                and order.execution_unknown is True
                and order.cancel_pending is None
            )
            known_broker_join = (
                state in {"ACCEPTED", "PARTIAL"}
                and type(order.broker_order_ref) is int
                and order.broker_order_ref > 0
                and order.execution_unknown is False
                and order.cancel_pending is False
            )
            invalid_state = not (known_remote_only or known_broker_join)
            duplicate = not common_invalid and order_key in observed_order_keys
            invalid = common_invalid or invalid_state or duplicate
        else:
            invalid = (
                common_invalid
                or state not in {"ACCEPTED", "PARTIAL"}
                or order.owner_strategy_scope != facts.strategy_scope
                or _exact_text(order.owner_intent_id) is None
                or order.execution_unknown is not False
                or order.cancel_pending is not False
                or type(order.broker_order_ref) is not int
                or order.broker_order_ref <= 0
            )
        if invalid:
            block("read_only_working_order_projection_invalid:{}".format(order.order_ref))
        else:
            observed_order_keys.add(order_key)
            observed_orders_by_target.setdefault(target_id, []).append(order)

    query_by_family = {fact.family: fact for fact in provenance if fact.family in _BASE_FAMILIES}
    for trade in facts.trade_observations:
        query = query_by_family.get("trades_result")
        if (
            query is None
            or trade.snapshot_id != facts.snapshot_id
            or trade.request_id != query.request_id
            or trade.connection_generation != query.connection_generation
            or trade.account_fingerprint != query.account_fingerprint
            or trade.trading_day != query.trading_day
            or trade.available_at != query.completed_at
        ):
            block("read_only_trade_observation_binding_mismatch")
    trade_query = query_by_family.get("trades_result")
    if trade_query is None or trade_query.row_count != len(facts.trade_observations):
        block("read_only_trade_observation_coverage_mismatch")

    orders_query = query_by_family.get("orders_result")
    for terminal in facts.terminal_orders:
        if (
            orders_query is None
            or terminal.snapshot_id != facts.snapshot_id
            or terminal.request_id != orders_query.request_id
            or terminal.connection_generation != orders_query.connection_generation
            or terminal.account_fingerprint != orders_query.account_fingerprint
            or terminal.trading_day != orders_query.trading_day
            or terminal.available_at != orders_query.completed_at
        ):
            block("read_only_terminal_order_binding_mismatch")

    ignored_prefixes = (
        "consumed_quote_",
        "consumed_stream_",
        "route_ineligible:",
        "route_eligibility_incomplete:",
        "route_arm_",
        "route_active_grant_unavailable:",
        # The Strategy's route-planning predicate also requires trading-ready.
        # Read-only retirement independently checks the exact account/day/
        # generation triple above, so this blocker may only reflect readiness.
        "route_current_session_identity_mismatch:",
        "instrument_multiplier_unobserved:",
        "instrument_tick_unobserved:",
        "instrument_limits_unobserved:",
        "instrument_tradability_unobserved:",
        "instrument_not_trading:",
    )
    for code in facts.blockers:
        if allow_unowned_state and type(code) is str:
            if code in external_position_blockers:
                continue
            # Foreign ownership is a strict reconciliation blocker.  It may
            # be tolerated only by the passive observation path below; generic
            # dated-proof blockers remain hard failures because they can also
            # indicate missing or contradictory source evidence.
            if code == "POSITION_OWNED_BY_OTHER_STRATEGY" and valid_foreign_target_ids:
                foreign_target_ids = {
                    _exact_text(position.target_id)
                    for position in target_positions
                    if position.position_book_status == "FOREIGN_OWNER"
                }
                if foreign_target_ids == valid_foreign_target_ids:
                    continue
            if code.startswith(
                (
                    "position_foreign_owner:",
                    "position_owner_scope_unobserved:",
                    "position_owner_intent_unobserved:",
                )
            ):
                target_id = code.rpartition(":")[2]
                if target_id in valid_foreign_target_ids:
                    continue
            if code.startswith("remote_working_order_missing_from_broker:"):
                ref = code.partition(":")[2]
                if any(
                    order.order_ref == ref and order.state == "REMOTE_ONLY"
                    for orders in observed_orders_by_target.values()
                    for order in orders
                ):
                    continue
            if code.startswith("working_order_owner_unobserved:"):
                ref = code.partition(":")[2]
                if any(
                    order.order_ref == ref
                    for orders in observed_orders_by_target.values()
                    for order in orders
                ):
                    continue
            if code == "INSTRUMENT_ORDER_UNRESOLVED":
                affected = tuple(
                    position
                    for position in positions
                    if position.position_book_status == "UNKNOWN"
                    and position.position_book_blocker_code == code
                )
                if affected and all(
                    any(
                        order.target_id == position.target_id
                        and order.instrument == position.instrument
                        and order.exchange == position.exchange
                        for order in observed_orders_by_target.get(position.target_id, ())
                    )
                    for position in affected
                ):
                    continue
        if (
            type(code) is str
            and not code.startswith(ignored_prefixes)
            and not _is_capital_blocker(code)
            and not code.startswith(
                (
                    "position_held_age_unavailable:",
                    "position_opening_fee_unavailable:",
                    "position_risk_policy_metadata_unavailable:",
                    "position_average_price_unobserved:",
                    "position_stop_price_unobserved:",
                )
            )
        ):
            blockers.add(code)
    return tuple(sorted(blockers))


def _dated_close_positions_ready(facts: FactorExecutionFacts) -> bool:
    """Require source-backed date legs for every nonflat SHFE/INE holding."""

    dated_exchanges = {"SHFE", "INE"}
    for position in facts.positions:
        if position.exchange.upper() not in dated_exchanges:
            continue
        if position.quantity is None or position.quantity == 0:
            continue
        target_id = position.target_id
        if target_id is None:
            return False
        legs = tuple(
            leg
            for leg in facts.dated_close_legs
            if leg.target_id == target_id
            and leg.instrument == position.instrument
            and leg.exchange == position.exchange
        )
        if not legs:
            return False
        expected_side = "LONG" if position.quantity > 0 else "SHORT"
        expected_order_side = "SELL" if position.quantity > 0 else "BUY"
        if position.long_quantity is None or position.short_quantity is None:
            return False
        if (
            position.quantity > 0
            and (position.long_quantity != position.quantity or position.short_quantity != 0)
        ) or (
            position.quantity < 0
            and (position.short_quantity != -position.quantity or position.long_quantity != 0)
        ):
            return False
        if any(
            not leg.ready
            or leg.blockers
            or leg.position_side != expected_side
            or leg.side != expected_order_side
            or leg.offset_flag != ("3" if leg.position_date == "TODAY" else "4")
            or leg.offset != ("close_today" if leg.position_date == "TODAY" else "close_yesterday")
            or leg.owner_strategy_scope != facts.strategy_scope
            or leg.owner_intent_id != position.owner_intent_id
            or leg.query_set_id != facts.query_set_id
            or facts.account is None
            or leg.account_fingerprint != facts.account.account_fingerprint
            or leg.connection_generation != facts.account.connection_generation
            or leg.trading_day != facts.account.trading_day
            or leg.snapshot_id != facts.snapshot_id
            or leg.available_at != facts.available_at
            or leg.available_quantity is None
            or leg.available_quantity <= 0
            or leg.available_quantity != leg.provider_quantity
            or leg.owned_quantity != leg.provider_quantity
            or leg.provider_quantity != leg.provider_quantity.to_integral_value()
            or not leg.source_row_ids
            or not leg.opening_execution_ids
            or not leg.lots
            for leg in legs
        ):
            return False
        if sum((leg.available_quantity for leg in legs), Decimal(0)) != abs(position.quantity):
            return False
        if len({(leg.position_date, leg.hedge_flag) for leg in legs}) != len(legs):
            return False
        if any(
            order.instrument == position.instrument and order.exchange == position.exchange
            for order in facts.working_orders
        ):
            return False
    return True


def _is_capital_blocker(code: str) -> bool:
    return code in _CAPITAL_BLOCKERS or code.startswith(
        (
            "margin_",
            "query_failed:instrument_margin_rate_result:",
            "query_facts_invalid:instrument_margin_rate_result:",
            "query_snapshot_read_failed:instrument_margin_rate_result:",
            "margin_query_identity_mismatch:",
            "long_margin_per_hand_unobserved:",
            "short_margin_per_hand_unobserved:",
        )
    )


def _exact_owned_cancel_join_covers_book_blocker(facts: FactorExecutionFacts) -> bool:
    """Prove that the Book's active-order reservation has a cancellable join.

    This exception affects only order-cancel blocker classification. It does
    not change position attribution, close readiness, or read-only retirement.
    Every position carrying this exact Book blocker must be covered by a current
    target order, and every projected working order must have an exact route,
    native session, owner, and active state. Order-query mismatch blockers stay
    in ``facts.blockers`` and are never filtered here.
    """

    if (
        facts.snapshot_id is None
        or facts.query_set_id is None
        or facts.available_at is None
        or facts.account is None
        or facts.account.account_scope != facts.account_scope
        or facts.account.snapshot_id != facts.snapshot_id
        or _aware_utc(facts.account.available_at) != facts.available_at
        or not _base_query_provenance_complete(facts.query_provenance, facts.available_at)
    ):
        return False
    affected = tuple(
        position
        for position in facts.positions
        if position.position_book_status == "UNKNOWN"
        and position.position_book_blocker_code == "INSTRUMENT_ORDER_UNRESOLVED"
    )
    if not affected or not facts.working_orders:
        return False

    positions_by_target = {}
    for position in facts.positions:
        target_id = position.target_id
        if (
            target_id is None
            or target_id in positions_by_target
            or position.snapshot_id != facts.snapshot_id
            or _aware_utc(position.available_at) != facts.available_at
        ):
            return False
        positions_by_target[target_id] = position

    order_keys = set()
    for order in facts.working_orders:
        key = (order.order_ref, order.instrument, order.exchange)
        if (
            order.target_id is None
            or order.target_id not in positions_by_target
            or order.order_ref != _exact_text(order.order_ref)
            or order.instrument != positions_by_target[order.target_id].instrument
            or order.exchange != positions_by_target[order.target_id].exchange
            or order.state not in {"ACCEPTED", "PARTIAL"}
            or order.side not in {"BUY", "SELL"}
            or order.position_effect not in {"OPEN", "CLOSE"}
            or type(order.remaining_quantity) is not Decimal
            or not order.remaining_quantity.is_finite()
            or order.remaining_quantity <= 0
            or order.owner_strategy_scope != facts.strategy_scope
            or _exact_text(order.owner_intent_id) is None
            or order.execution_unknown is not False
            or order.cancel_pending is not False
            or type(order.broker_order_ref) is not int
            or order.broker_order_ref <= 0
            or type(order.front_id) is not int
            or order.front_id <= 0
            or type(order.session_id) is not int
            or order.session_id <= 0
            or key in order_keys
        ):
            return False
        order_keys.add(key)

    return all(
        any(
            order.target_id == position.target_id
            and order.instrument == position.instrument
            and order.exchange == position.exchange
            for order in facts.working_orders
        )
        for position in affected
    )


def _is_open_risk_only_blocker(code: str) -> bool:
    """Classify risk-capacity/policy uncertainty without erasing reductions.

    These codes describe opening policy/capacity inputs, average/stop metadata,
    fees, or holding age. They do not vouch for ownership, quantity, route, or
    quote; those remain independent reduction-critical facts checked by
    ``risk_reduction_ready``.
    """

    return code.startswith(
        (
            "position_held_age_unavailable:",
            "position_opening_fee_unavailable:",
            "position_risk_policy_metadata_unavailable:",
            "position_average_price_unobserved:",
            "position_stop_price_unobserved:",
        )
    ) or code in {
        "OPEN_INTENT_QUANTITY_EXCEEDED",
        "POSITION_GRID_ANCHOR_UNAVAILABLE",
        "POSITION_GRID_CURSOR_UNAVAILABLE",
        "POSITION_RISK_METADATA_UNAVAILABLE",
    }


def _unmatched_trade_diagnostic(
    *,
    health_count: Optional[int],
    trade_rows: Any,
    order_rows: Any,
    observations: Tuple[FactorExecutionTradeObservationFacts, ...],
    blockers: List[str],
) -> Tuple[str, ...]:
    """Cross-check the Store's aggregate count against exact parsed query rows.

    The count is diagnostic after this bridge has the complete row set. The
    coordinator still proves every trade row independently; malformed,
    omitted, or count-mismatched evidence remains a blocker.
    """

    if health_count is None:
        return ()
    if not isinstance(trade_rows, list) or not isinstance(order_rows, list):
        blockers.append("ctp_unmatched_trade_observation_coverage_unavailable")
        return ()
    if len(observations) != len(trade_rows):
        blockers.append("ctp_unmatched_trade_observation_coverage_mismatch")
        return ()
    order_refs = set()
    for row in order_rows:
        if not isinstance(row, Mapping):
            blockers.append("ctp_unmatched_order_reference_unobserved")
            return ()
        order_ref = _exact_text(row.get("OrderRef", row.get("order_ref")))
        if order_ref is None:
            blockers.append("ctp_unmatched_order_reference_unobserved")
            return ()
        order_refs.add(order_ref)
    expected_count = sum(item.order_ref not in order_refs for item in observations)
    if health_count != expected_count:
        blockers.append("ctp_unmatched_trade_count_mismatch")
        return ()
    if expected_count > 0:
        return ("ctp_unmatched_trade_rows_present:{}".format(expected_count),)
    return ()


def _base_query_provenance_complete(
    provenance: Tuple[FactorExecutionQueryFact, ...],
    available_at: datetime,
) -> bool:
    base = [fact for fact in provenance if fact.family in _BASE_FAMILIES]
    if len(base) != len(_BASE_FAMILIES) or {fact.family for fact in base} != set(_BASE_FAMILIES):
        return False
    if any(
        fact.request_type != _REQUEST_TYPES[fact.family]
        or fact.request_id is None
        or fact.connection_generation is None
        or fact.account_fingerprint is None
        or fact.trading_day is None
        or fact.started_at is None
        or fact.completed_at is None
        or fact.started_at > fact.completed_at
        or fact.completed_at > available_at
        or not fact.source_owned
        or not fact.query_complete
        or fact.scope_complete is not True
        for fact in base
    ):
        return False
    return (
        len({fact.request_id for fact in base}) == len(_BASE_FAMILIES)
        and len({fact.connection_generation for fact in base}) == 1
        and len({fact.account_fingerprint for fact in base}) == 1
        and len({fact.trading_day for fact in base}) == 1
    )


def _field(value: Any, name: str, default: Any = None) -> Any:
    if isinstance(value, Mapping):
        return value.get(name, default)
    return getattr(value, name, default)


def _aware_utc(value: Any) -> Optional[datetime]:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        return None
    return value.astimezone(timezone.utc)


def _decimal(value: Any, *, nonnegative: bool = False, positive: bool = False) -> Optional[Decimal]:
    if (
        value is None
        or isinstance(value, bool)
        or not isinstance(value, (str, int, float, Decimal))
    ):
        return None
    try:
        result = Decimal(str(value).strip())
    except (InvalidOperation, ValueError, OverflowError):
        return None
    if not result.is_finite() or (nonnegative and result < 0) or (positive and result <= 0):
        return None
    return result


def _integer(value: Any, *, allow_zero: bool = True) -> Optional[int]:
    number = _decimal(value, nonnegative=allow_zero)
    if number is None or number != number.to_integral_value():
        return None
    result = int(number)
    if result < 0 or (not allow_zero and result == 0):
        return None
    return result


def _epoch_datetime(value: Any) -> Optional[datetime]:
    direct = _aware_utc(value)
    if direct is not None:
        return direct
    number = _decimal(value, positive=True)
    if number is None:
        return None
    try:
        return datetime.fromtimestamp(float(number), tz=timezone.utc)
    except (OverflowError, OSError, ValueError):
        return None


def _bool_fact(value: Any) -> Optional[bool]:
    if type(value) is bool:
        return value
    if type(value) is int and value in (0, 1):
        return bool(value)
    if type(value) is str:
        normalized = value.strip().lower()
        if normalized in {"1", "true", "yes"}:
            return True
        if normalized in {"0", "false", "no"}:
            return False
    return None


def _exact_text(value: Any) -> Optional[str]:
    if type(value) is str and value and value == value.strip():
        return value
    return None


def _query_fact(
    family: str, result: Any, *, target_id: Optional[str] = None
) -> FactorExecutionQueryFact:
    rows = _field(result, "rows")
    row_count = len(rows) if isinstance(rows, (tuple, list)) else None
    request_id = _field(result, "request_id")
    generation = _field(result, "connection_generation")
    scope_complete = _field(result, "scope_complete")
    return FactorExecutionQueryFact(
        family=family,
        request_type=_exact_text(_field(result, "request_type")),
        request_id=request_id if type(request_id) is int and request_id > 0 else None,
        connection_generation=generation if type(generation) is int and generation > 0 else None,
        account_fingerprint=_exact_text(_field(result, "account_fingerprint")),
        trading_day=_exact_text(_field(result, "trading_day")),
        started_at=_aware_utc(_field(result, "started_at_utc")),
        completed_at=_aware_utc(_field(result, "completed_at_utc")),
        source_owned=_field(result, "source_owned") is True,
        query_complete=_field(result, "query_complete") is True,
        scope_complete=scope_complete if type(scope_complete) is bool else None,
        row_count=row_count,
        target_id=target_id,
    )


def _missing_query_fact(family: str, target_id: Optional[str] = None) -> FactorExecutionQueryFact:
    return FactorExecutionQueryFact(
        family=family,
        request_type=None,
        request_id=None,
        connection_generation=None,
        account_fingerprint=None,
        trading_day=None,
        started_at=None,
        completed_at=None,
        source_owned=False,
        query_complete=False,
        scope_complete=None,
        row_count=None,
        target_id=target_id,
    )


def _query_valid(
    family: str,
    result: Any,
    *,
    now: datetime,
    max_age: timedelta,
    require_full_scope: bool,
    expected_filters: Optional[Mapping] = None,
) -> bool:
    fact = _query_fact(family, result)
    completed = fact.completed_at
    started = fact.started_at
    rows = _field(result, "rows")
    source_filters = _field(result, "source_explicit_request_filters")
    filters = _field(result, "query_filters")
    return bool(
        _field(result, "family") == family
        and fact.request_type == _REQUEST_TYPES.get(family)
        and _field(result, "expected_request_type") == _REQUEST_TYPES.get(family)
        and fact.request_id is not None
        and fact.connection_generation is not None
        and fact.trading_day is not None
        and len(fact.trading_day) == 8
        and fact.trading_day.isdigit()
        and started is not None
        and completed is not None
        and started <= completed <= now
        and now - completed <= max_age
        and fact.source_owned
        and fact.query_complete
        and _field(result, "complete") is True
        and _field(result, "is_last_seen") is True
        and _field(result, "timed_out") is False
        and _field(result, "error_code_observed") is True
        and (
            _field(result, "error_code") is None
            or type(_field(result, "error_code")) is int
            and _field(result, "error_code") == 0
        )
        and _field(result, "error_message") == ""
        and _field(result, "unsupported") is False
        and _field(result, "late_callback_count") == 0
        and _field(result, "submit_code_observed") is True
        and (
            _field(result, "submit_code") is None
            or type(_field(result, "submit_code")) is int
            and _field(result, "submit_code") == 0
        )
        and isinstance(rows, list)
        and all(isinstance(row, Mapping) and bool(row) for row in rows)
        and isinstance(source_filters, tuple)
        and (source_filters == () if require_full_scope else source_filters == _MARGIN_FILTERS)
        and (fact.scope_complete is True if require_full_scope else fact.scope_complete is False)
        and (
            dict(filters) == dict(expected_filters or {}) if expected_filters is not None else True
        )
    )


def _query_set_identifier(
    account_fingerprint: str,
    generation: int,
    trading_day: str,
    started_at: datetime,
    completed_at: datetime,
    query_ids: Tuple[Tuple[str, int], ...],
) -> str:
    payload = json.dumps(
        (
            "factor-execution-query-set-v1",
            account_fingerprint,
            generation,
            trading_day,
            started_at.isoformat(),
            completed_at.isoformat(),
            query_ids,
        ),
        ensure_ascii=True,
        separators=(",", ":"),
    ).encode("ascii")
    return "ctp.query-set:" + hashlib.sha256(payload).hexdigest()


def _completed_query_set(
    *,
    include_core: bool,
    attempted: List[str],
    pending: List[str],
    provenance: List[FactorExecutionQueryFact],
    completed_at: datetime,
) -> Optional[FactorExecutionQuerySetFacts]:
    """Seal only a single successful batch of all five unfiltered core reads."""

    if not include_core or tuple(attempted[: len(_BASE_FAMILIES)]) != _BASE_FAMILIES:
        return None
    if any(family in _BASE_FAMILIES for family in pending):
        return None
    facts_by_family = {
        fact.family: fact
        for fact in provenance
        if fact.family in _BASE_FAMILIES and fact.target_id is None
    }
    if set(facts_by_family) != set(_BASE_FAMILIES):
        return None
    facts = tuple(facts_by_family[family] for family in _BASE_FAMILIES)
    if any(
        fact.request_type != _REQUEST_TYPES[family]
        or fact.request_id is None
        or fact.connection_generation is None
        or fact.account_fingerprint is None
        or fact.trading_day is None
        or fact.started_at is None
        or fact.completed_at is None
        or fact.started_at > fact.completed_at
        or fact.completed_at > completed_at
        or not fact.source_owned
        or not fact.query_complete
        or fact.scope_complete is not True
        for family, fact in zip(_BASE_FAMILIES, facts)
    ):
        return None
    if (
        len({fact.request_id for fact in facts}) != len(_BASE_FAMILIES)
        or len({fact.connection_generation for fact in facts}) != 1
        or len({fact.account_fingerprint for fact in facts}) != 1
        or len({fact.trading_day for fact in facts}) != 1
    ):
        return None
    account_fingerprint = facts[0].account_fingerprint
    generation = facts[0].connection_generation
    trading_day = facts[0].trading_day
    query_ids = tuple((family, fact.request_id) for family, fact in zip(_BASE_FAMILIES, facts))
    batch_started = min(fact.started_at for fact in facts)
    batch_completed = max(fact.completed_at for fact in facts)
    if batch_completed > completed_at:
        return None
    identifier = _query_set_identifier(
        account_fingerprint,
        generation,
        trading_day,
        batch_started,
        batch_completed,
        query_ids,
    )
    return FactorExecutionQuerySetFacts(
        query_set_id=identifier,
        account_fingerprint=account_fingerprint,
        connection_generation=generation,
        trading_day=trading_day,
        started_at_utc=batch_started,
        completed_at_utc=batch_completed,
        query_ids=query_ids,
    )


def _query_set_matches(
    query_set: Any,
    facts: Tuple[FactorExecutionQueryFact, ...],
    *,
    now: datetime,
    max_age: timedelta,
) -> bool:
    if type(query_set) is not FactorExecutionQuerySetFacts:
        return False
    if (
        type(query_set.account_fingerprint) is not str
        or not query_set.account_fingerprint
        or type(query_set.connection_generation) is not int
        or query_set.connection_generation <= 0
        or type(query_set.trading_day) is not str
        or len(query_set.trading_day) != 8
        or not query_set.trading_day.isdigit()
        or _aware_utc(query_set.started_at_utc) is None
        or _aware_utc(query_set.completed_at_utc) is None
        or query_set.started_at_utc > query_set.completed_at_utc
        or query_set.completed_at_utc > now
        or now - query_set.completed_at_utc > max_age
        or not isinstance(query_set.query_ids, tuple)
        or len(query_set.query_ids) != len(_BASE_FAMILIES)
        or any(
            not isinstance(item, tuple)
            or len(item) != 2
            or type(item[0]) is not str
            or type(item[1]) is not int
            for item in query_set.query_ids
        )
        or tuple(family for family, _request_id in query_set.query_ids) != _BASE_FAMILIES
    ):
        return False
    expected = tuple((family, fact.request_id) for family, fact in zip(_BASE_FAMILIES, facts))
    if query_set.query_ids != expected:
        return False
    if any(
        fact.account_fingerprint != query_set.account_fingerprint
        or fact.connection_generation != query_set.connection_generation
        or fact.trading_day != query_set.trading_day
        or fact.started_at is None
        or fact.completed_at is None
        or fact.started_at < query_set.started_at_utc
        or fact.completed_at > query_set.completed_at_utc
        for fact in facts
    ):
        return False
    if (
        min(fact.started_at for fact in facts) != query_set.started_at_utc
        or max(fact.completed_at for fact in facts) != query_set.completed_at_utc
    ):
        return False
    return query_set.query_set_id == _query_set_identifier(
        query_set.account_fingerprint,
        query_set.connection_generation,
        query_set.trading_day,
        query_set.started_at_utc,
        query_set.completed_at_utc,
        query_set.query_ids,
    )


def _position_side(value: Any) -> Optional[str]:
    if type(value) is int:
        value = str(value)
    if type(value) is not str:
        return None
    normalized = value.strip().upper()
    if normalized in {"2", "LONG", "BUY"}:
        return "LONG"
    if normalized in {"3", "SHORT", "SELL"}:
        return "SHORT"
    return None


def _order_side(value: Any) -> Optional[str]:
    if type(value) is int:
        value = str(value)
    if type(value) is not str:
        return None
    normalized = value.strip().upper()
    if normalized in {"0", "BUY", "B"}:
        return "BUY"
    if normalized in {"1", "SELL", "S"}:
        return "SELL"
    return None


def _position_effect(value: Any) -> Optional[str]:
    if isinstance(value, (tuple, list)):
        value = value[0] if value else None
    if type(value) is int:
        value = str(value)
    if type(value) is not str:
        return None
    normalized = value.strip().upper()
    if normalized in {"0", "OPEN"}:
        return "OPEN"
    if normalized in {"1", "2", "3", "4", "5", "6", "CLOSE"}:
        return "CLOSE"
    return None


def _active_remote_order(row: Mapping) -> Optional[bool]:
    raw = row.get("OrderStatus", row.get("order_status"))
    if type(raw) is int:
        raw = str(raw)
    if type(raw) is not str:
        return None
    status = raw.strip().lower()
    if status in {
        "0",
        "2",
        "4",
        "5",
        "alltraded",
        "parttradednotqueueing",
        "notradingnotqueueing",
        "canceled",
        "cancelled",
    }:
        return False
    if status in {
        "1",
        "3",
        "b",
        "c",
        "parttradedqueueing",
        "notradequeueing",
        "nottouched",
        "touched",
    }:
        return True
    if status == "a":
        # CTP's Unknown order state may still represent live native exposure.
        return True
    return None


def _remote_ref(value: Any) -> Optional[str]:
    if type(value) is str and value and value == value.strip():
        return value
    if type(value) is int and value >= 0:
        return str(value)
    return None


def _position_rows(rows: Any, blockers: List[str]):
    projected = defaultdict(lambda: {"LONG": Decimal(0), "SHORT": Decimal(0)})
    if not isinstance(rows, list):
        blockers.append("positions_rows_unobserved")
        return None
    valid = True
    for row in rows:
        if not isinstance(row, Mapping):
            blockers.append("position_row_shape_invalid")
            valid = False
            continue
        instrument = _exact_text(row.get("InstrumentID", row.get("instrument_id")))
        exchange = _exact_text(row.get("ExchangeID", row.get("exchange_id")))
        side = _position_side(row.get("PosiDirection", row.get("position_direction")))
        quantity = _decimal(row.get("Position", row.get("position")), nonnegative=True)
        if instrument is None or exchange is None or side is None or quantity is None:
            blockers.append("position_row_fields_unobserved")
            valid = False
            continue
        projected[(instrument, exchange)][side] += quantity
    return dict(projected) if valid else None


def _ctp_single_char(value: Any) -> Optional[str]:
    """Keep a CTP char field exact while accepting its integer test form."""

    if type(value) is str and len(value) == 1 and not value.isspace():
        return value
    if type(value) is int and 0 <= value <= 9:
        return str(value)
    return None


def _position_dated_inventory_rows(
    rows: Any,
    *,
    query_fact: FactorExecutionQueryFact,
    query_set_id: str,
    snapshot_id: str,
    available_at: datetime,
    blockers: List[str],
) -> Tuple[FactorExecutionDatedInventoryRow, ...]:
    """Copy explicit CTP date buckets without deriving history by subtraction.

    The current balance is always ``Position`` for that exact source row.
    ``TodayPosition`` is used only as a consistency field. ``YdPosition`` is
    retained as the reported prior-day baseline and is never converted into a
    current HISTORY quantity.
    """

    if not isinstance(rows, list):
        blockers.append("dated_inventory_rows_unobserved")
        return ()
    if (
        query_fact.family != "positions_result"
        or query_fact.request_type != "positions"
        or query_fact.request_id is None
        or query_fact.connection_generation is None
        or query_fact.account_fingerprint is None
        or query_fact.trading_day is None
        or query_fact.completed_at is None
        or query_fact.source_owned is not True
        or query_fact.query_complete is not True
        or query_fact.scope_complete is not True
    ):
        blockers.append("dated_inventory_query_provenance_unavailable")
        return ()

    projected = []
    freeze_fields = (
        ("LongFrozen", "long_frozen", "long_frozen"),
        ("ShortFrozen", "short_frozen", "short_frozen"),
        ("CombLongFrozen", "comb_long_frozen", "comb_long_frozen"),
        ("CombShortFrozen", "comb_short_frozen", "comb_short_frozen"),
        ("StrikeFrozen", "strike_frozen", "strike_frozen"),
        ("AbandonFrozen", "abandon_frozen", "abandon_frozen"),
        ("LongFrozenAmount", "long_frozen_amount", "long_frozen_amount"),
        ("ShortFrozenAmount", "short_frozen_amount", "short_frozen_amount"),
        ("FrozenMargin", "frozen_margin", "frozen_margin"),
        ("FrozenCash", "frozen_cash", "frozen_cash"),
        ("FrozenCommission", "frozen_commission", "frozen_commission"),
        ("StrikeFrozenAmount", "strike_frozen_amount", "strike_frozen_amount"),
        ("YdStrikeFrozen", "yd_strike_frozen", "yd_strike_frozen"),
    )
    for ordinal, row in enumerate(rows):
        row_blockers = []
        if not isinstance(row, Mapping):
            row_blockers.append("ROW_SHAPE_INVALID")
            row = {}
        observed = []

        def source_value(
            canonical: str,
            alias: str,
            *,
            source_row=row,
            observed_fields=observed,
        ):
            if canonical in source_row:
                observed_fields.append(canonical)
                return source_row[canonical]
            if alias in source_row:
                observed_fields.append(alias)
                return source_row[alias]
            return None

        instrument = _exact_text(source_value("InstrumentID", "instrument_id"))
        exchange = _exact_text(source_value("ExchangeID", "exchange_id"))
        side_code = _ctp_single_char(source_value("PosiDirection", "position_direction"))
        side = _position_side(side_code)
        hedge_flag = _ctp_single_char(source_value("HedgeFlag", "hedge_flag"))
        date_code = _ctp_single_char(source_value("PositionDate", "position_date"))
        position_date = {"1": "TODAY", "2": "HISTORY"}.get(date_code)
        row_trading_day = _exact_text(source_value("TradingDay", "trading_day"))
        position = _decimal(source_value("Position", "position"), nonnegative=True)
        today_position = _decimal(source_value("TodayPosition", "today_position"), nonnegative=True)
        yd_position = _decimal(source_value("YdPosition", "yd_position"), nonnegative=True)
        freeze_values = {}
        for canonical, alias, name in freeze_fields:
            freeze_values[name] = _decimal(source_value(canonical, alias), nonnegative=True)

        if instrument is None or exchange is None:
            row_blockers.append("ROUTE_IDENTITY_UNOBSERVED")
        if side is None:
            row_blockers.append("POSITION_SIDE_UNOBSERVED")
        if hedge_flag not in {"1", "2", "3", "5"}:
            row_blockers.append("HEDGE_FLAG_UNSUPPORTED_OR_UNOBSERVED")
        if position_date is None:
            row_blockers.append("POSITION_DATE_UNSUPPORTED_OR_UNOBSERVED")
        if (
            row_trading_day is None
            or len(row_trading_day) != 8
            or not row_trading_day.isdigit()
            or row_trading_day != query_fact.trading_day
        ):
            row_blockers.append("POSITION_TRADING_DAY_MISSING_OR_MISMATCH")
        if position is None:
            row_blockers.append("POSITION_QUANTITY_UNOBSERVED")
        if today_position is None:
            row_blockers.append("TODAY_POSITION_UNOBSERVED")
        if yd_position is None:
            row_blockers.append("YESTERDAY_BASELINE_UNOBSERVED")
        if any(value is None for value in freeze_values.values()):
            row_blockers.append("POSITION_FREEZE_FIELDS_UNOBSERVED")
        elif any(value != 0 for value in freeze_values.values()):
            row_blockers.append("POSITION_FREEZE_PRESENT")
        if position_date == "TODAY" and (
            position is None or today_position is None or position != today_position
        ):
            row_blockers.append("TODAY_POSITION_CONTRADICTION")
        if position_date == "HISTORY" and today_position != 0:
            row_blockers.append("HISTORY_TODAY_POSITION_CONTRADICTION")

        row_id = "positions-query-row:{}:{}".format(query_fact.request_id, ordinal)
        immutable_blockers = tuple(sorted(set(row_blockers)))
        projected.append(
            FactorExecutionDatedInventoryRow(
                instrument=instrument or "",
                exchange=exchange or "",
                position_side=side,
                hedge_flag=hedge_flag,
                position_date_code=date_code,
                position_date=position_date,
                trading_day=row_trading_day,
                position=position,
                today_position=today_position,
                yd_position=yd_position,
                long_frozen=freeze_values["long_frozen"],
                short_frozen=freeze_values["short_frozen"],
                comb_long_frozen=freeze_values["comb_long_frozen"],
                comb_short_frozen=freeze_values["comb_short_frozen"],
                strike_frozen=freeze_values["strike_frozen"],
                abandon_frozen=freeze_values["abandon_frozen"],
                long_frozen_amount=freeze_values["long_frozen_amount"],
                short_frozen_amount=freeze_values["short_frozen_amount"],
                frozen_margin=freeze_values["frozen_margin"],
                frozen_cash=freeze_values["frozen_cash"],
                frozen_commission=freeze_values["frozen_commission"],
                strike_frozen_amount=freeze_values["strike_frozen_amount"],
                yd_strike_frozen=freeze_values["yd_strike_frozen"],
                observed_fields=tuple(observed),
                source_row_id=row_id,
                query_set_id=query_set_id,
                snapshot_id=snapshot_id,
                request_id=query_fact.request_id,
                connection_generation=query_fact.connection_generation,
                account_fingerprint=query_fact.account_fingerprint,
                available_at=query_fact.completed_at,
                blockers=immutable_blockers,
            )
        )
    return tuple(projected)


def _account_values(rows: Any, blockers: List[str]):
    if not isinstance(rows, list) or len(rows) != 1 or not isinstance(rows[0], Mapping):
        blockers.append("account_row_cardinality_unobserved")
        return None, None
    available = _decimal(rows[0].get("Available", rows[0].get("available")), nonnegative=True)
    used = _decimal(rows[0].get("CurrMargin", rows[0].get("current_margin")), nonnegative=True)
    if available is None:
        blockers.append("available_margin_unobserved")
    if used is None:
        blockers.append("used_margin_unobserved")
    return available, used


def _instrument_row(rows: Any, instrument: str, exchange: str, blockers: List[str]):
    if not isinstance(rows, list):
        blockers.append("instrument_rows_unobserved:{}".format(instrument))
        return None
    matches = [
        row
        for row in rows
        if isinstance(row, Mapping)
        and row.get("InstrumentID", row.get("instrument_id")) == instrument
        and row.get("ExchangeID", row.get("exchange_id")) == exchange
    ]
    if len(matches) != 1:
        blockers.append("instrument_metadata_cardinality:{}".format(instrument))
        return None
    return matches[0]


def _margin_rates(rows: Any, instrument: str, exchange: str, blockers: List[str]):
    if not isinstance(rows, list):
        blockers.append("margin_rows_unobserved:{}".format(instrument))
        return None
    matches = [
        row
        for row in rows
        if isinstance(row, Mapping)
        and row.get("InstrumentID", row.get("instrument_id")) == instrument
        and row.get("ExchangeID", row.get("exchange_id")) == exchange
        and str(row.get("HedgeFlag", row.get("hedge_flag", ""))).strip() == "1"
    ]
    if len(matches) != 1:
        blockers.append("margin_metadata_cardinality:{}".format(instrument))
        return None
    row = matches[0]
    values = tuple(
        _decimal(row.get(name), nonnegative=True)
        for name in (
            "LongMarginRatioByMoney",
            "LongMarginRatioByVolume",
            "ShortMarginRatioByMoney",
            "ShortMarginRatioByVolume",
        )
    )
    if any(value is None for value in values):
        blockers.append("margin_rates_unobserved:{}".format(instrument))
        return None
    return values


def _valid_targets(targets: Tuple[FactorExecutionTarget, ...]) -> Tuple[FactorExecutionTarget, ...]:
    items = tuple(targets)
    if not items or any(not isinstance(item, FactorExecutionTarget) for item in items):
        raise ValueError("targets must contain FactorExecutionTarget values")
    if len({item.target_id for item in items}) != len(items):
        raise ValueError("target ids must be unique")
    # Store's consumed tick getter and Broker's exact data binding are keyed
    # by instrument.  Duplicate aliases would make that join ambiguous.
    if len({item.instrument for item in items}) != len(items):
        raise ValueError("target instruments must be unique")
    if len({(item.instrument, item.exchange) for item in items}) != len(items):
        raise ValueError("target instrument routes must be unique")
    # Alpha003 and its live target pools are not restricted to the 32-asset
    # research smoke fixture.  Keep an explicit finite upper bound while
    # letting the runner refresh large configured pools incrementally.
    if len(items) > 256:
        raise ValueError("target count exceeds bounded refresh limit")
    return items


def refresh_factor_execution_queries(
    store: RegisteredSimStore,
    *,
    targets: Tuple[FactorExecutionTarget, ...],
    timeout: float = 8.0,
    overall_timeout: float = 60.0,
    include_core: bool = True,
    margin_target_ids: Optional[Tuple[str, ...]] = None,
    max_queries: Optional[int] = None,
    cancel_event: Optional[threading.Event] = None,
) -> FactorExecutionRefreshReceipt:
    """Refresh typed CTP query evidence from a runner-owned control path.

    Queries are serialized. The caller can refresh the five complete core
    families once, then refresh target margin families incrementally between
    engine-idle windows with ``include_core=False`` and an explicit subset of
    ``margin_target_ids``. ``max_queries`` caps one batch. A ``threading.Event``
    prevents further calls after the current synchronous query returns. Each
    call receives at most ``timeout`` and the remaining overall budget. The
    SDK query method must honor that timeout; the receipt retains pending work
    if the budget/cancellation stops the batch. This must not run from
    ``Strategy.next``.
    """

    if not isinstance(store, RegisteredSimStore):
        raise TypeError("store must be a RegisteredSimStore")
    bound_targets = _valid_targets(tuple(targets))
    for name, value in (("timeout", timeout), ("overall_timeout", overall_timeout)):
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ValueError("{} must be finite and positive".format(name))
        if not math.isfinite(float(value)) or float(value) <= 0:
            raise ValueError("{} must be finite and positive".format(name))
    if float(timeout) > 8.0:
        raise ValueError("per-query timeout cannot exceed 8 seconds")
    if type(include_core) is not bool:
        raise ValueError("include_core must be bool")
    if cancel_event is not None and not isinstance(cancel_event, _THREADING_EVENT_TYPE):
        raise TypeError("cancel_event must be a threading.Event")
    targets_by_id = {target.target_id: target for target in bound_targets}
    selected_margin_ids = (
        tuple(targets_by_id) if margin_target_ids is None else tuple(margin_target_ids)
    )
    if any(type(value) is not str or value not in targets_by_id for value in selected_margin_ids):
        raise ValueError("margin_target_ids must name configured targets")
    if len(set(selected_margin_ids)) != len(selected_margin_ids):
        raise ValueError("margin_target_ids must be unique")
    if max_queries is not None and (type(max_queries) is not int or max_queries <= 0):
        raise ValueError("max_queries must be a positive int")

    started_at = datetime.now(timezone.utc)
    start_mono = time.monotonic()
    deadline = start_mono + float(overall_timeout)
    requested = list(_BASE_FAMILIES) if include_core else []
    margin_specs = [
        (
            targets_by_id[target_id],
            {
                "instrument_id": targets_by_id[target_id].instrument,
                "exchange_id": targets_by_id[target_id].exchange,
                "hedge_flag": "1",
            },
        )
        for target_id in selected_margin_ids
    ]
    requested.extend(
        "instrument_margin_rate_result:{}".format(target.target_id)
        for target, _filters in margin_specs
    )
    if not requested:
        raise ValueError("refresh must request core or at least one target margin family")

    blockers: List[str] = []
    attempted: List[str] = []
    provenance: List[FactorExecutionQueryFact] = []
    queries = [(family, None, {}) for family in _BASE_FAMILIES] if include_core else []
    queries.extend(
        ("instrument_margin_rate_result", target, filters) for target, filters in margin_specs
    )
    pending = []
    cancelled = False
    query_limit = len(queries) if max_queries is None else min(max_queries, len(queries))
    for index, (family, target, filters) in enumerate(queries):
        if index >= query_limit:
            pending.extend(
                pending_family
                if pending_target is None
                else "{}:{}".format(pending_family, pending_target.target_id)
                for pending_family, pending_target, _filters in queries[index:]
            )
            break
        if cancel_event is not None and cancel_event.is_set():
            cancelled = True
            blockers.append(
                "query_refresh_cancelled_before:{}".format(
                    family if target is None else "{}:{}".format(family, target.target_id)
                )
            )
            pending.extend(
                pending_family
                if pending_target is None
                else "{}:{}".format(pending_family, pending_target.target_id)
                for pending_family, pending_target, _filters in queries[index:]
            )
            break
        remaining = deadline - time.monotonic()
        label = family if target is None else "{}:{}".format(family, target.target_id)
        if remaining <= 0:
            blockers.append("query_refresh_deadline_before:{}".format(label))
            pending.extend(
                pending_family
                if pending_target is None
                else "{}:{}".format(pending_family, pending_target.target_id)
                for pending_family, pending_target, _filters in queries[index:]
            )
            break
        attempted.append(label)
        try:
            result = store.registered_sim_query(
                family, timeout=min(float(timeout), remaining), attempts=1, **filters
            )
        except Exception as exc:
            result = None
            blockers.append("query_refresh_failed:{}:{}".format(label, type(exc).__name__))
        if result is None:
            provenance.append(_missing_query_fact(family, target.target_id if target else None))
        else:
            provenance.append(
                _query_fact(family, result, target_id=target.target_id if target else None)
            )
    completed_at = datetime.now(timezone.utc)
    deadline_reached = time.monotonic() >= deadline
    if deadline_reached:
        blockers.append("query_refresh_overall_deadline_reached")
    query_set = _completed_query_set(
        include_core=include_core,
        attempted=attempted,
        pending=pending,
        provenance=provenance,
        completed_at=completed_at,
    )
    return FactorExecutionRefreshReceipt(
        started_at=started_at,
        completed_at=completed_at,
        requested_families=tuple(requested),
        attempted_families=tuple(attempted),
        query_provenance=tuple(provenance),
        blockers=tuple(sorted(set(blockers))),
        deadline_reached=deadline_reached,
        pending_families=tuple(pending),
        cancelled=cancelled,
        query_set=query_set,
    )


def _route_fact(
    store: RegisteredSimStore,
    target: FactorExecutionTarget,
    *,
    query_identity: Optional[Tuple[int, str, str]],
    blockers: List[str],
) -> FactorExecutionRouteFacts:
    try:
        route = store.registered_sim_route_eligibility(target.instrument, target.exchange)
    except Exception as exc:
        blockers.append(
            "route_eligibility_unobserved:{}:{}".format(target.target_id, type(exc).__name__)
        )
        return FactorExecutionRouteFacts(
            target_id=target.target_id,
            instrument=target.instrument,
            exchange=target.exchange,
            route_name=None,
            eligible=None,
            allow_writes=None,
            frozen=None,
            capability_observed=None,
            capability_managed=None,
            capability_armed=None,
            capability_matches_route=None,
            instrument_query_complete=None,
            instrument_eligible=None,
            unknown_order_count=None,
            dispatching_order_count=None,
            connection_generation=None,
            trading_day=None,
            reason_codes=(),
            sdk_frozen=None,
            arm_template_configured=None,
            arm_templates_configured=None,
            arm_template_membership=None,
            arm_api_available=None,
            current_session_account_fingerprint=None,
            current_session_connection_generation=None,
            current_session_trading_day=None,
            current_session_trading_ready=None,
        )

    unknown_count = _field(route, "unknown_order_count")
    dispatching_ids = _field(route, "dispatching_order_ids")
    dispatching_count = len(dispatching_ids) if isinstance(dispatching_ids, (tuple, list)) else None
    route_generation = _field(route, "connection_generation")
    route_day = _exact_text(_field(route, "trading_day"))
    account_fingerprint = _exact_text(_field(route, "account_fingerprint"))
    identity_matches = bool(
        query_identity is not None
        and type(route_generation) is int
        and route_generation > 0
        and route_generation == query_identity[0]
        and route_day == query_identity[1]
        and account_fingerprint == query_identity[2]
    )

    def optional_bool(name: str) -> Optional[bool]:
        value = _field(route, name)
        return value if type(value) is bool else None

    template_configured = optional_bool("arm_template_configured")
    templates_configured = optional_bool("arm_templates_configured")
    template_membership = optional_bool("arm_template_membership")
    arm_api_available = optional_bool("arm_api_available")
    current_session_account = _exact_text(_field(route, "current_session_account_fingerprint"))
    current_session_generation = _field(route, "current_session_connection_generation")
    current_session_day = _exact_text(_field(route, "current_session_trading_day"))
    current_session_trading_ready = optional_bool("current_session_trading_ready")
    current_session_matches = bool(
        query_identity is not None
        and current_session_trading_ready is True
        and type(current_session_generation) is int
        and current_session_generation > 0
        and current_session_generation == query_identity[0]
        and current_session_day == query_identity[1]
        and current_session_account == query_identity[2]
    )

    active_grant_matches = bool(
        _field(route, "capability_observed") is True
        and _field(route, "sdk_capability_managed") is True
        and _field(route, "sdk_capability_armed") is True
        and _field(route, "capability_matches_route") is True
    )
    template_mode = bool(
        templates_configured is True and template_configured is True and arm_api_available is True
    )
    legacy_active_mode = bool(
        templates_configured is False and template_configured is False and active_grant_matches
    )
    template_scope_consistent = bool(
        (templates_configured is True and template_configured is True)
        or (templates_configured is False and template_configured is False)
    )

    common_positive_facts = bool(
        _field(route, "route_name") == "ctp/direct/registered-sim"
        and _field(route, "instrument_id") == target.instrument
        and _field(route, "exchange_id") == target.exchange
        and _field(route, "allow_writes") is True
        and _field(route, "frozen") is False
        and _field(route, "sdk_frozen") is False
        and _field(route, "capability_observed") is True
        and _field(route, "instrument_query_complete") is True
        and _field(route, "instrument_eligible") is True
        and type(unknown_count) is int
        and unknown_count == 0
        and _field(route, "unknown_order_ids") == ()
        and dispatching_ids == ()
        and identity_matches
        and current_session_matches
        and template_scope_consistent
    )
    positives = bool(common_positive_facts and (template_mode or legacy_active_mode))

    explicit_denial = bool(
        _field(route, "instrument_id") not in (None, target.instrument)
        or _field(route, "exchange_id") not in (None, target.exchange)
        or _field(route, "allow_writes") is False
        or _field(route, "frozen") is True
        or _field(route, "sdk_frozen") is True
        or _field(route, "instrument_eligible") is False
        or (type(unknown_count) is int and unknown_count > 0)
        or (isinstance(dispatching_ids, (tuple, list)) and bool(dispatching_ids))
        or current_session_trading_ready is False
        or (templates_configured is True and template_configured is not True)
        or (
            templates_configured is True
            and template_configured is True
            and arm_api_available is False
        )
        or (
            templates_configured is False
            and template_configured is False
            and (
                _field(route, "sdk_capability_armed") is False
                or _field(route, "capability_matches_route") is False
            )
        )
        or (
            templates_configured is False
            and template_configured is False
            and _field(route, "sdk_capability_managed") is False
        )
    )
    eligible = True if positives else False if explicit_denial else None
    if eligible is True:
        pass
    elif eligible is False:
        blockers.append("route_ineligible:{}".format(target.target_id))
    else:
        blockers.append("route_eligibility_incomplete:{}".format(target.target_id))
    if not identity_matches:
        blockers.append("route_query_identity_mismatch:{}".format(target.target_id))
    if not current_session_matches:
        blockers.append("route_current_session_identity_mismatch:{}".format(target.target_id))
    if templates_configured is True and template_configured is True:
        if arm_api_available is False:
            blockers.append("route_arm_api_unavailable:{}".format(target.target_id))
        elif arm_api_available is None:
            blockers.append("route_arm_api_unobserved:{}".format(target.target_id))
    elif templates_configured is True and template_configured is not True:
        blockers.append("route_arm_template_missing:{}".format(target.target_id))
    elif templates_configured is False and template_configured is False:
        if not active_grant_matches:
            blockers.append("route_active_grant_unavailable:{}".format(target.target_id))
    else:
        blockers.append("route_arm_template_state_unobserved:{}".format(target.target_id))
    raw_reasons = _field(route, "reason_codes")
    reasons = (
        tuple(value for value in raw_reasons if type(value) is str)
        if isinstance(raw_reasons, (tuple, list))
        else ()
    )

    return FactorExecutionRouteFacts(
        target_id=target.target_id,
        instrument=target.instrument,
        exchange=target.exchange,
        route_name=_exact_text(_field(route, "route_name")),
        eligible=eligible,
        allow_writes=optional_bool("allow_writes"),
        frozen=optional_bool("frozen"),
        capability_observed=optional_bool("capability_observed"),
        capability_managed=optional_bool("sdk_capability_managed"),
        capability_armed=optional_bool("sdk_capability_armed"),
        capability_matches_route=optional_bool("capability_matches_route"),
        instrument_query_complete=optional_bool("instrument_query_complete"),
        instrument_eligible=optional_bool("instrument_eligible"),
        unknown_order_count=unknown_count
        if type(unknown_count) is int and unknown_count >= 0
        else None,
        dispatching_order_count=dispatching_count,
        connection_generation=route_generation if type(route_generation) is int else None,
        trading_day=route_day,
        reason_codes=reasons,
        sdk_frozen=optional_bool("sdk_frozen"),
        arm_template_configured=template_configured,
        arm_templates_configured=templates_configured,
        arm_template_membership=template_membership,
        arm_api_available=arm_api_available,
        current_session_account_fingerprint=current_session_account,
        current_session_connection_generation=(
            current_session_generation if type(current_session_generation) is int else None
        ),
        current_session_trading_day=current_session_day,
        current_session_trading_ready=current_session_trading_ready,
    )


def _quote_fact(
    store: RegisteredSimStore,
    target: FactorExecutionTarget,
    *,
    instrument_fact: Optional[FactorExecutionInstrumentFacts],
    snapshot_id: Optional[str],
    generation: Optional[int],
    trading_day: Optional[str],
    available_at: Optional[datetime],
    now: datetime,
    max_age: timedelta,
    blockers: List[str],
) -> FactorExecutionQuoteFacts:
    quality = "GOOD"
    try:
        tick = store.get_latest_tick_snapshot(target.instrument)
    except Exception as exc:
        tick = None
        quality = "READ_FAILED"
        blockers.append(
            "consumed_tick_read_failed:{}:{}".format(target.target_id, type(exc).__name__)
        )

    try:
        stream_ready = store.is_stream_ready(target.instrument)
    except Exception as exc:
        stream_ready = None
        blockers.append(
            "consumed_stream_state_read_failed:{}:{}".format(target.target_id, type(exc).__name__)
        )

    source = _exact_text(_field(tick, "source"))
    source_ref = _exact_text(_field(tick, "event_id"))
    tick_trading_day = _exact_text(_field(tick, "trading_day"))
    # The route-bound source is a public, immutable RegisteredSimStore
    # contract.  Do not derive it from caller-supplied provenance mappings or
    # from the consumed tick itself: either can repeat an untrusted label.
    registered_source = getattr(store, "registered_sim_tick_source", None)
    expected_source = _exact_text(registered_source)
    tick_generation = _field(tick, "connection_generation")
    stream_generation = _field(tick, "stream_generation")
    sequence = _field(tick, "sequence")
    ingest_sequence = _field(tick, "ingest_seq")
    event_time = _epoch_datetime(_field(tick, "exchange_time"))
    received_at = _epoch_datetime(_field(tick, "received_wall_time"))
    bid = _decimal(_field(tick, "bid_price"), positive=True)
    ask = _decimal(_field(tick, "ask_price"), positive=True)
    bid_size = _decimal(_field(tick, "bid_volume"), positive=True)
    ask_size = _decimal(_field(tick, "ask_volume"), positive=True)

    def fail(code: str, next_quality: str) -> None:
        nonlocal quality
        if quality == "GOOD":
            quality = next_quality
        blockers.append("{}:{}".format(code, target.target_id))

    if tick is None:
        quality = "UNAVAILABLE"
        fail("consumed_quote_unavailable", quality)
    else:
        if stream_ready is not True:
            fail(
                "consumed_stream_not_currently_ready",
                "STREAM_NOT_READY" if stream_ready is False else "STREAM_READINESS_UNOBSERVED",
            )
        if (
            _field(tick, "instrument_id") != target.instrument
            or _field(tick, "exchange_id") != target.exchange
        ):
            fail("consumed_quote_identity_mismatch", "IDENTITY_MISMATCH")
        if source is None or source_ref is None:
            fail("consumed_quote_source_unobserved", "PROVENANCE_UNOBSERVED")
        if expected_source is None and registered_source is None:
            fail("consumed_quote_registered_source_unobserved", "PROVENANCE_UNOBSERVED")
        elif expected_source is None:
            fail("consumed_quote_registered_source_invalid", "PROVENANCE_INVALID")
        elif source is not None and source != expected_source:
            fail("consumed_quote_registered_source_mismatch", "SOURCE_MISMATCH")
        if tick_trading_day is None or trading_day is None or tick_trading_day != trading_day:
            fail("consumed_quote_trading_day_mismatch", "TRADING_DAY_MISMATCH")
        if (
            type(tick_generation) is not int
            or tick_generation <= 0
            or tick_generation != generation
            or stream_generation != tick_generation
        ):
            fail("consumed_quote_generation_mismatch", "GENERATION_MISMATCH")
        if (
            type(sequence) is not int
            or sequence <= 0
            or type(ingest_sequence) is not int
            or sequence != ingest_sequence
        ):
            fail("consumed_quote_sequence_unobserved", "SEQUENCE_UNOBSERVED")
        if _field(tick, "stale") is not False or _field(tick, "continuity_status") != "continuous":
            fail("consumed_quote_not_continuous", "STALE_OR_GAPPED")
        if _field(tick, "snapshot_or_delta") != "snapshot" or _field(tick, "coalesced_count") != 1:
            fail("consumed_quote_envelope_unusable", "UNSUPPORTED_TICK_ENVELOPE")
        if event_time is None or received_at is None:
            fail("consumed_quote_time_unobserved", "TIME_UNOBSERVED")
        else:
            event_age = now - event_time
            receive_age = now - received_at
            if event_age < timedelta(0) or receive_age < timedelta(0):
                fail("consumed_quote_from_future", "FUTURE")
            elif event_age > max_age or receive_age > max_age:
                fail("consumed_quote_stale", "STALE")
            if available_at is None or event_time < available_at or received_at < available_at:
                fail("consumed_quote_before_risk_snapshot", "OLDER_THAN_RISK_SNAPSHOT")
            if received_at < event_time:
                fail("consumed_quote_clock_order_invalid", "TIME_ORDER_INVALID")
        if bid is None or ask is None or bid_size is None or ask_size is None or bid > ask:
            fail("consumed_quote_book_unusable", "BOOK_UNOBSERVED")
    return FactorExecutionQuoteFacts(
        instrument=target.instrument,
        exchange=target.exchange,
        source=source,
        source_ref=source_ref,
        metadata_snapshot_id=snapshot_id,
        generation=tick_generation if type(tick_generation) is int else None,
        sequence=sequence if type(sequence) is int else None,
        trading_day=tick_trading_day,
        event_time=event_time,
        available_at=received_at,
        bid=bid,
        ask=ask,
        bid_size=bid_size,
        ask_size=ask_size,
        tick_size=instrument_fact.tick_size if instrument_fact is not None else None,
        lower_limit=instrument_fact.lower_limit if instrument_fact is not None else None,
        upper_limit=instrument_fact.upper_limit if instrument_fact is not None else None,
        quality=quality,
    )


def _broker_position_snapshot(broker: Any, target: FactorExecutionTarget, blockers: List[str]):
    method = getattr(broker, "execution_position_snapshot", None)
    if not callable(method):
        blockers.append("broker_no_io_position_projection_unavailable")
        return None
    try:
        snapshot = method(target.data)
    except Exception as exc:
        blockers.append(
            "broker_position_projection_failed:{}:{}".format(target.target_id, type(exc).__name__)
        )
        return None
    if snapshot is None:
        blockers.append("broker_position_projection_unavailable:{}".format(target.target_id))
        return None
    if (
        _field(snapshot, "instrument_id") != target.instrument
        or _field(snapshot, "exchange_id") != target.exchange
    ):
        blockers.append("broker_position_identity_mismatch:{}".format(target.target_id))
        return None
    quantity = _decimal(_field(snapshot, "quantity"))
    long_qty = _decimal(_field(snapshot, "long_quantity"), nonnegative=True)
    short_qty = _decimal(_field(snapshot, "short_quantity"), nonnegative=True)
    average_price = _decimal(_field(snapshot, "average_price"), positive=True)
    if any(value is None for value in (quantity, long_qty, short_qty)):
        blockers.append("broker_position_quantity_unobserved:{}".format(target.target_id))
        return None
    return snapshot, quantity, long_qty, short_qty, average_price


def _position_facts(
    broker: Any,
    targets: Tuple[FactorExecutionTarget, ...],
    remote_positions: Any,
    *,
    coordinator: Any,
    account_scope: str,
    strategy_scope: str,
    snapshot_id: str,
    available_at: datetime,
    dated_inventory_by_route: Mapping,
    blockers: List[str],
) -> Tuple[FactorExecutionPositionFacts, ...]:
    if remote_positions is None:
        return ()
    target_by_route = {(target.instrument, target.exchange): target for target in targets}
    for (instrument, exchange), sides in remote_positions.items():
        if sides["LONG"] or sides["SHORT"]:
            if (instrument, exchange) not in target_by_route:
                blockers.append(
                    "external_position_outside_target_scope:{}:{}".format(instrument, exchange)
                )
    book = _field(coordinator, "position_book")
    snapshot_method = getattr(book, "snapshot", None)
    if not callable(snapshot_method):
        blockers.append("position_book_projection_unavailable")
        return ()
    projected = []
    for (instrument, exchange), sides in sorted(remote_positions.items()):
        if (instrument, exchange) in target_by_route or not (sides["LONG"] or sides["SHORT"]):
            continue
        opposing = bool(sides["LONG"] and sides["SHORT"])
        projected.append(
            FactorExecutionPositionFacts(
                target_id=None,
                instrument=instrument,
                exchange=exchange,
                quantity=None if opposing else sides["LONG"] - sides["SHORT"],
                snapshot_id=snapshot_id,
                available_at=available_at,
                owner_strategy_scope=None,
                owner_intent_id=None,
                average_price=None,
                stop_price=None,
                held_eligible_bars=None,
                long_quantity=sides["LONG"],
                short_quantity=sides["SHORT"],
                broker_quantity=None,
                opening_fee_total=None,
                opening_fees_known=None,
                dated_inventory_rows=tuple(
                    dated_inventory_by_route.get((instrument, exchange), ())
                ),
            )
        )
        if opposing:
            blockers.append(
                "external_opposing_position_sides_present:{}:{}".format(instrument, exchange)
            )
    for target in targets:
        broker_state = _broker_position_snapshot(broker, target, blockers)
        ctp = remote_positions.get(
            (target.instrument, target.exchange),
            {"LONG": Decimal(0), "SHORT": Decimal(0)},
        )
        long_qty, short_qty = ctp["LONG"], ctp["SHORT"]
        if broker_state is None:
            projected.append(
                FactorExecutionPositionFacts(
                    target_id=target.target_id,
                    instrument=target.instrument,
                    exchange=target.exchange,
                    quantity=None,
                    snapshot_id=snapshot_id,
                    available_at=available_at,
                    owner_strategy_scope=None,
                    owner_intent_id=None,
                    average_price=None,
                    stop_price=None,
                    held_eligible_bars=None,
                    long_quantity=long_qty,
                    short_quantity=short_qty,
                    broker_quantity=None,
                    opening_fee_total=None,
                    opening_fees_known=None,
                    dated_inventory_rows=tuple(
                        dated_inventory_by_route.get((target.instrument, target.exchange), ())
                    ),
                )
            )
            continue
        _broker, broker_qty, broker_long, broker_short, broker_average = broker_state
        if broker_long and broker_short:
            blockers.append("opposing_broker_position_sides_present:{}".format(target.target_id))
        if long_qty and short_qty:
            blockers.append("opposing_position_sides_present:{}".format(target.instrument))
        side_mismatch = broker_long != long_qty or broker_short != short_qty
        if side_mismatch:
            blockers.append("broker_ctp_position_side_mismatch:{}".format(target.target_id))
        broker_net_mismatch = broker_qty != broker_long - broker_short
        if broker_net_mismatch:
            blockers.append("broker_position_net_mismatch:{}".format(target.target_id))
        # Keep the actual cached Broker value even when CTP sides disagree.
        # The disagreement stays an explicit blocker and the position book
        # independently decides whether any durable attribution is provable.
        broker_quantity = broker_qty
        try:
            book_snapshot = snapshot_method(
                account_scope=account_scope,
                strategy_scope=strategy_scope,
                instrument=target.instrument,
                exchange=target.exchange,
                broker_quantity=broker_qty,
                long_quantity=long_qty,
                short_quantity=short_qty,
                snapshot_id=snapshot_id,
                available_at=available_at,
            )
        except Exception as exc:
            book_snapshot = None
            error_code = _exact_text(_field(exc, "code"))
            blockers.append(
                "position_book_projection_failed:{}:{}:{}".format(
                    target.target_id, type(exc).__name__, error_code or "code_unavailable"
                )
            )
        if book_snapshot is not None:
            binding_matches = bool(
                _field(book_snapshot, "account_scope") == account_scope
                and _field(book_snapshot, "strategy_scope") == strategy_scope
                and _field(book_snapshot, "instrument") == target.instrument
                and _field(book_snapshot, "exchange") == target.exchange
                and _field(book_snapshot, "snapshot_id") == snapshot_id
                and _aware_utc(_field(book_snapshot, "available_at")) == available_at
            )
            if not binding_matches:
                blockers.append(
                    "position_book_snapshot_binding_mismatch:{}".format(target.target_id)
                )
                book_snapshot = None
        status = _exact_text(_field(book_snapshot, "status"))
        book_blocker = _exact_text(_field(book_snapshot, "blocker_code"))
        book_quantity = _decimal(_field(book_snapshot, "signed_quantity"))
        # Quantity remains the exact Broker/CTP position projection.  The
        # position book adds attribution; it never replaces this quantity.
        quantity = broker_qty
        attributed_quantity = _decimal(_field(book_snapshot, "attributed_signed_quantity"))
        if status == "FLAT":
            if broker_qty != 0 or long_qty != 0 or short_qty != 0 or quantity != 0:
                blockers.append("position_book_flat_binding_mismatch:{}".format(target.target_id))
                quantity = None
                broker_quantity = None
            else:
                quantity = broker_quantity = Decimal(0)
        elif broker_quantity is not None and book_quantity != broker_qty:
            blockers.append("position_book_quantity_mismatch:{}".format(target.target_id))
        owner_scope = _exact_text(_field(book_snapshot, "owner_strategy_scope"))
        owner_intent = _exact_text(_field(book_snapshot, "owner_intent_id"))
        average_price = _decimal(_field(book_snapshot, "average_price"), positive=True)
        stop_price = _decimal(_field(book_snapshot, "stop_price"), positive=True)
        held_bars = _integer(_field(book_snapshot, "held_eligible_bars"))
        opening_fee_total = _decimal(_field(book_snapshot, "opening_fee_total"), nonnegative=True)
        opening_fees_known_raw = _field(book_snapshot, "opening_fees_known")
        opening_fees_known = (
            opening_fees_known_raw if type(opening_fees_known_raw) is bool else None
        )
        if status == "FLAT":
            pass
        elif status == "RISK_METADATA_MISSING":
            blockers.append("position_risk_policy_metadata_unavailable:{}".format(target.target_id))
        elif status == "UNKNOWN" and book_blocker in {
            "POSITION_GRID_ANCHOR_UNAVAILABLE",
            "POSITION_GRID_CURSOR_UNAVAILABLE",
        }:
            # This only withholds the hold-age cursor.  Any owner, quantity,
            # average, and stop the book actually returned remain available.
            blockers.append("position_held_age_unavailable:{}".format(target.target_id))
        elif status != "MATCHED":
            blockers.append(
                book_blocker or "position_attribution_unavailable:{}".format(target.target_id)
            )
        if quantity not in (None, Decimal(0)) and owner_scope != strategy_scope:
            blockers.append("position_foreign_owner:{}".format(target.target_id))
        if quantity not in (None, Decimal(0)):
            if owner_scope is None:
                blockers.append("position_owner_scope_unobserved:{}".format(target.target_id))
            if owner_intent is None:
                blockers.append("position_owner_intent_unobserved:{}".format(target.target_id))
            if average_price is None:
                blockers.append("position_average_price_unobserved:{}".format(target.target_id))
            if stop_price is None:
                blockers.append("position_stop_price_unobserved:{}".format(target.target_id))
            if held_bars is None:
                blockers.append("position_held_age_unavailable:{}".format(target.target_id))
            if opening_fees_known is not True or opening_fee_total is None:
                # CTP full-trade queries carry no fee.  Keep actual fees
                # explicitly unavailable; this can constrain increases, but
                # never masks already-proven ownership or authorized exits.
                opening_fee_total = None
                opening_fees_known = False
                blockers.append("position_opening_fee_unavailable:{}".format(target.target_id))
        # Prefer the journal's execution-derived average for an owned position;
        # Broker's average remains an independent projection, never attribution.
        projected.append(
            FactorExecutionPositionFacts(
                target_id=target.target_id,
                instrument=target.instrument,
                exchange=target.exchange,
                quantity=quantity,
                snapshot_id=snapshot_id,
                available_at=available_at,
                owner_strategy_scope=owner_scope,
                owner_intent_id=owner_intent,
                average_price=average_price,
                stop_price=stop_price,
                held_eligible_bars=held_bars,
                long_quantity=long_qty,
                short_quantity=short_qty,
                broker_quantity=broker_quantity,
                attributed_signed_quantity=attributed_quantity,
                opening_fee_total=opening_fee_total,
                opening_fees_known=opening_fees_known,
                dated_inventory_rows=tuple(
                    dated_inventory_by_route.get((target.instrument, target.exchange), ())
                ),
                position_book_status=status,
                position_book_blocker_code=book_blocker,
            )
        )
    return tuple(projected)


def _remote_order_rows(rows: Any, blockers: List[str], *, expected_trading_day: Optional[str]):
    active = {}
    if not isinstance(rows, list):
        blockers.append("remote_orders_rows_unobserved")
        return None
    valid = True
    for row in rows:
        if not isinstance(row, Mapping):
            blockers.append("remote_order_row_shape_invalid")
            valid = False
            continue
        ref = _remote_ref(row.get("OrderRef", row.get("order_ref")))
        instrument = _exact_text(row.get("InstrumentID", row.get("instrument_id")))
        exchange = _exact_text(row.get("ExchangeID", row.get("exchange_id")))
        is_active = _active_remote_order(row)
        trading_day = _exact_text(row.get("TradingDay", row.get("trading_day")))
        if (
            trading_day is None
            or len(trading_day) != 8
            or not trading_day.isdigit()
            or expected_trading_day is None
            or trading_day != expected_trading_day
        ):
            blockers.append("remote_order_trading_day_unobserved_or_mismatch")
            valid = False
            continue
        if ref is None or instrument is None or exchange is None or is_active is None:
            blockers.append("remote_order_identity_or_state_unobserved")
            valid = False
            continue
        if not is_active:
            continue
        key = (ref, instrument, exchange)
        if key in active:
            blockers.append("remote_order_identity_duplicate:{}".format(ref))
            valid = False
            continue
        active[key] = row
    return active if valid else None


def _terminal_order_facts(
    rows: Any,
    *,
    query_fact: FactorExecutionQueryFact,
    snapshot_id: str,
    blockers: List[str],
) -> Tuple[FactorExecutionTerminalOrderFacts, ...]:
    """Project explicit terminal rows from the validated full orders query."""

    if (
        query_fact.family != "orders_result"
        or query_fact.request_type != "orders"
        or query_fact.request_id is None
        or query_fact.connection_generation is None
        or query_fact.account_fingerprint is None
        or query_fact.trading_day is None
        or query_fact.completed_at is None
        or not query_fact.source_owned
        or not query_fact.query_complete
        or query_fact.scope_complete is not True
        or not isinstance(rows, list)
    ):
        return ()

    status_map = {
        "0": "ALL_TRADED",
        "alltraded": "ALL_TRADED",
        "2": "PART_TRADED_NOT_QUEUEING",
        "parttradednotqueueing": "PART_TRADED_NOT_QUEUEING",
        "4": "NO_TRADE_NOT_QUEUEING",
        "notradingnotqueueing": "NO_TRADE_NOT_QUEUEING",
        "notradenotqueueing": "NO_TRADE_NOT_QUEUEING",
        "5": "CANCELED",
        "canceled": "CANCELED",
        "cancelled": "CANCELED",
    }
    projected = []
    by_native_ref = {}
    duplicate_refs = set()
    for row in rows:
        if not isinstance(row, Mapping):
            continue
        raw_status = row.get("OrderStatus", row.get("order_status"))
        if type(raw_status) is int:
            source_status = str(raw_status)
        elif type(raw_status) is str and raw_status == raw_status.strip():
            source_status = raw_status
        else:
            continue
        terminal_state = status_map.get(source_status.lower())
        if terminal_state is None:
            continue
        order_ref = _remote_ref(row.get("OrderRef", row.get("order_ref")))
        instrument = _exact_text(row.get("InstrumentID", row.get("instrument_id")))
        exchange = _exact_text(row.get("ExchangeID", row.get("exchange_id")))
        order_sys_id = _remote_ref(row.get("OrderSysID", row.get("order_sys_id")))
        row_trading_day = _exact_text(row.get("TradingDay", row.get("trading_day")))
        if (
            row_trading_day is None
            or len(row_trading_day) != 8
            or not row_trading_day.isdigit()
            or row_trading_day != query_fact.trading_day
        ):
            blockers.append(
                "remote_terminal_order_trading_day_mismatch:{}".format(order_ref or "unknown")
            )
            continue
        if order_ref is None or instrument is None or exchange is None:
            continue
        identity = (order_ref, instrument, exchange)
        if identity in by_native_ref:
            # A duplicate native ref is ambiguous even when a second row adds
            # a different optional OrderSysID. Never select one as authority.
            duplicate_refs.add(identity)
            continue
        by_native_ref[identity] = len(projected)
        identity_payload = json.dumps(
            (
                "ctp-orders-query-observation-v1",
                query_fact.connection_generation,
                query_fact.trading_day,
                query_fact.request_id,
                order_ref,
                order_sys_id,
                instrument,
                exchange,
                source_status,
            ),
            ensure_ascii=True,
            separators=(",", ":"),
        ).encode("ascii")
        observation_id = "orders-query-row:" + hashlib.sha256(identity_payload).hexdigest()
        projected.append(
            FactorExecutionTerminalOrderFacts(
                instrument=instrument,
                exchange=exchange,
                order_ref=order_ref,
                order_sys_id=order_sys_id,
                terminal_status=source_status,
                terminal_state=terminal_state,
                observation_id=observation_id,
                evidence_kind="complete_orders_query_observation",
                snapshot_id=snapshot_id,
                request_id=query_fact.request_id,
                connection_generation=query_fact.connection_generation,
                account_fingerprint=query_fact.account_fingerprint,
                trading_day=query_fact.trading_day,
                available_at=query_fact.completed_at,
                front_id=_integer(row.get("FrontID", row.get("front_id")), allow_zero=False),
                session_id=_integer(row.get("SessionID", row.get("session_id")), allow_zero=False),
                volume_total_original=_decimal(
                    row.get("VolumeTotalOriginal", row.get("volume_total_original")),
                    nonnegative=True,
                ),
                volume_traded=_decimal(
                    row.get("VolumeTraded", row.get("volume_traded")), nonnegative=True
                ),
                volume_total=_decimal(
                    row.get("VolumeTotal", row.get("volume_total")), nonnegative=True
                ),
            )
        )
    if duplicate_refs:
        blockers.extend(
            "remote_terminal_order_identity_duplicate:{}:{}:{}".format(*identity)
            for identity in sorted(duplicate_refs)
        )
        projected = [
            item
            for item in projected
            if (item.order_ref, item.instrument, item.exchange) not in duplicate_refs
        ]
    return tuple(
        sorted(projected, key=lambda item: (item.instrument, item.exchange, item.order_ref))
    )


def _trade_observation_facts(
    rows: Any,
    *,
    query_fact: FactorExecutionQueryFact,
    snapshot_id: str,
    blockers: List[str],
) -> Tuple[FactorExecutionTradeObservationFacts, ...]:
    """Project real trade rows without inventing callback, time, or fee facts."""

    if (
        query_fact.family != "trades_result"
        or query_fact.request_type != "trades"
        or query_fact.request_id is None
        or query_fact.connection_generation is None
        or query_fact.account_fingerprint is None
        or query_fact.trading_day is None
        or query_fact.completed_at is None
        or not query_fact.source_owned
        or not query_fact.query_complete
        or query_fact.scope_complete is not True
    ):
        return ()
    if not isinstance(rows, list):
        blockers.append("remote_trade_rows_unobserved")
        return ()

    observations = {}
    duplicates = set()
    ctp_timezone = timezone(timedelta(hours=8))
    for row in rows:
        if not isinstance(row, Mapping):
            blockers.append("remote_trade_row_shape_invalid")
            continue
        trade_id = _exact_text(row.get("TradeID", row.get("trade_id")))
        order_ref = _remote_ref(row.get("OrderRef", row.get("order_ref")))
        order_sys_id = _remote_ref(row.get("OrderSysID", row.get("order_sys_id")))
        instrument = _exact_text(row.get("InstrumentID", row.get("instrument_id")))
        exchange = _exact_text(row.get("ExchangeID", row.get("exchange_id")))
        row_trading_day = _exact_text(row.get("TradingDay", row.get("trading_day")))
        if (
            row_trading_day is None
            or len(row_trading_day) != 8
            or not row_trading_day.isdigit()
            or row_trading_day != query_fact.trading_day
        ):
            blockers.append("remote_trade_trading_day_mismatch:{}".format(trade_id or "unknown"))
            continue
        raw_direction = row.get("Direction", row.get("direction"))
        raw_offset = row.get("OffsetFlag", row.get("CombOffsetFlag", row.get("offset_flag")))
        raw_hedge = row.get("HedgeFlag", row.get("hedge_flag"))
        direction = _ctp_single_char(raw_direction)
        offset = _ctp_single_char(raw_offset)
        hedge_flag = _ctp_single_char(raw_hedge)
        side = _order_side(raw_direction)
        position_effect = _position_effect(raw_offset)
        volume = _decimal(row.get("Volume", row.get("volume")), positive=True)
        price = _decimal(row.get("Price", row.get("price")), positive=True)
        trade_date = _exact_text(row.get("TradeDate", row.get("trade_date")))
        trade_time = _exact_text(row.get("TradeTime", row.get("trade_time")))
        trade_time_utc = None
        if (
            trade_date is not None
            and len(trade_date) == 8
            and trade_date.isdigit()
            and trade_time is not None
            and len(trade_time) in range(8, 16)
            and trade_time[:8].count(":") == 2
        ):
            try:
                time_format = "%Y%m%d %H:%M:%S.%f" if "." in trade_time else "%Y%m%d %H:%M:%S"
                trade_time_utc = (
                    datetime.strptime("{} {}".format(trade_date, trade_time), time_format)
                    .replace(tzinfo=ctp_timezone)
                    .astimezone(timezone.utc)
                )
            except ValueError:
                trade_time_utc = None
        if (
            trade_id is None
            or order_ref is None
            or instrument is None
            or exchange is None
            or direction is None
            or side is None
            or offset is None
            or position_effect is None
            or volume is None
            or price is None
            or trade_time_utc is None
        ):
            blockers.append("remote_trade_fields_unobserved:{}".format(trade_id or "unknown"))
            continue
        if trade_time_utc > query_fact.completed_at:
            blockers.append("remote_trade_time_after_query:{}".format(trade_id))
            continue
        if trade_id in observations:
            duplicates.add(trade_id)
            continue
        identity_payload = json.dumps(
            (
                "ctp-trades-query-observation-v1",
                query_fact.connection_generation,
                query_fact.trading_day,
                query_fact.request_id,
                row_trading_day,
                trade_id,
                order_ref,
                order_sys_id,
                instrument,
                exchange,
                direction,
                offset,
                hedge_flag,
                str(volume),
                str(price),
                trade_date,
                trade_time,
            ),
            ensure_ascii=True,
            separators=(",", ":"),
        ).encode("ascii")
        observations[trade_id] = FactorExecutionTradeObservationFacts(
            trade_id=trade_id,
            order_ref=order_ref,
            order_sys_id=order_sys_id,
            instrument=instrument,
            exchange=exchange,
            direction=direction,
            side=side,
            offset=offset,
            position_effect=position_effect,
            volume=volume,
            price=price,
            trade_date=trade_date,
            trade_time=trade_time,
            trade_time_utc=trade_time_utc,
            fee=None,
            observation_id=("trades-query-row:" + hashlib.sha256(identity_payload).hexdigest()),
            evidence_kind="complete_trades_query_observation",
            snapshot_id=snapshot_id,
            request_id=query_fact.request_id,
            connection_generation=query_fact.connection_generation,
            account_fingerprint=query_fact.account_fingerprint,
            trading_day=query_fact.trading_day,
            available_at=query_fact.completed_at,
            hedge_flag=hedge_flag,
            offset_flag=offset,
        )
    for trade_id in sorted(duplicates):
        blockers.append("remote_trade_id_duplicate:{}".format(trade_id))
        observations.pop(trade_id, None)
    return tuple(
        sorted(
            observations.values(),
            key=lambda item: (item.trade_time_utc, item.trade_id),
        )
    )


def _trade_reconciliation_blockers(
    coordinator: Any, facts: FactorExecutionFacts
) -> Tuple[str, ...]:
    """Require bounded disposition proof for every complete-query trade row.

    ``EXTERNAL_FLAT`` is accepted only as the coordinator's positive
    no-journal disposition after it proves the same route flat from later
    complete CTP and cached Broker positions with no working order. Every
    owned row still requires its applied/duplicate journal receipt.
    """

    if not facts.trade_observations:
        return ()
    method = getattr(coordinator, "trade_reconciliation_snapshot", None)
    if not callable(method):
        return ("trade_observation_reconciliation_unavailable",)
    try:
        page = method(facts, limit=512, offset=0)
    except Exception as exc:
        return ("trade_observation_reconciliation_unavailable:{}".format(type(exc).__name__),)
    items = _field(page, "items")
    count = _field(page, "observation_count")
    if (
        not isinstance(items, tuple)
        or _field(page, "truncated") is not False
        or type(count) is not int
        or count != len(facts.trade_observations)
        or len(items) != count
    ):
        return ("trade_observation_reconciliation_incomplete",)
    observed = {}
    for item in items:
        observation_id = _exact_text(_field(item, "observation_id"))
        status = _exact_text(_field(item, "status"))
        if observation_id is None or observation_id in observed:
            return ("trade_observation_reconciliation_identity_invalid",)
        observed[observation_id] = item
        if status not in {"APPLIED", "DUPLICATE", "EXTERNAL_FLAT"}:
            code = _exact_text(_field(item, "blocker_code")) or status or "status_unobserved"
            return ("trade_observation_not_reconciled:{}:{}".format(observation_id, code),)
    expected = {item.observation_id for item in facts.trade_observations}
    if len(expected) != len(facts.trade_observations) or set(observed) != expected:
        return ("trade_observation_reconciliation_identity_mismatch",)
    return ()


def _terminal_order_reconciliation_blockers(
    coordinator: Any, facts: FactorExecutionFacts
) -> Tuple[str, ...]:
    """Require bounded journal proof for each complete-query terminal row.

    The public orders query is account-wide. Unmatched terminal rows remain
    blocked unless the coordinator proves the exact route is flat from later
    same-session CTP and cached Broker positions and has no working order.
    The runner may reconcile exact rows on its serialized control path; this
    projection only reads the coordinator's proof page.
    """

    if not facts.terminal_orders:
        return ()
    method = getattr(coordinator, "terminal_order_reconciliation_snapshot", None)
    if not callable(method):
        return ("terminal_order_reconciliation_unavailable",)
    try:
        page = method(facts, limit=512, offset=0)
    except Exception as exc:
        return ("terminal_order_reconciliation_unavailable:{}".format(type(exc).__name__),)
    items = _field(page, "items")
    count = _field(page, "observation_count")
    if (
        not isinstance(items, tuple)
        or _field(page, "truncated") is not False
        or type(count) is not int
        or count != len(facts.terminal_orders)
        or len(items) != count
    ):
        return ("terminal_order_reconciliation_incomplete",)
    observed = {}
    for item in items:
        observation_id = _exact_text(_field(item, "observation_id"))
        status = _exact_text(_field(item, "status"))
        if observation_id is None or observation_id in observed:
            return ("terminal_order_reconciliation_identity_invalid",)
        observed[observation_id] = item
        if status not in {"RESOLVED", "EXTERNAL_TERMINAL_FLAT"}:
            code = _exact_text(_field(item, "blocker_code")) or status or "status_unobserved"
            return ("terminal_order_not_reconciled:{}:{}".format(observation_id, code),)
    expected = {item.observation_id for item in facts.terminal_orders}
    if len(expected) != len(facts.terminal_orders) or set(observed) != expected:
        return ("terminal_order_reconciliation_identity_mismatch",)
    return ()


def _orders_facts(
    broker: Any,
    targets: Tuple[FactorExecutionTarget, ...],
    remote_rows: Any,
    *,
    coordinator: Any,
    trading_day: Optional[str],
    blockers: List[str],
) -> Tuple[FactorExecutionWorkingOrderFacts, ...]:
    order_method = getattr(broker, "execution_order_snapshot", None)
    intent_method = getattr(coordinator, "execution_intent_snapshot", None)
    if not callable(order_method):
        blockers.append("broker_order_projection_unavailable")
        broker_orders = None
    else:
        try:
            broker_orders = order_method()
        except Exception as exc:
            broker_orders = None
            blockers.append("broker_order_projection_failed:{}".format(type(exc).__name__))
        if not isinstance(broker_orders, tuple):
            broker_orders = None
            blockers.append("broker_order_projection_shape_invalid")
    if not callable(intent_method):
        blockers.append("journal_intent_projection_unavailable")
        intent_records = None
    else:
        try:
            intent_page = intent_method(limit=128)
        except Exception as exc:
            intent_page = None
            blockers.append("journal_intent_projection_failed:{}".format(type(exc).__name__))
        intent_records = _field(intent_page, "items")
        truncated = _field(intent_page, "truncated")
        if not isinstance(intent_records, tuple) or type(truncated) is not bool:
            intent_records = None
            blockers.append("journal_intent_projection_shape_invalid")
        elif truncated:
            blockers.append("journal_intent_projection_truncated")

    target_by_instrument = {target.instrument: target for target in targets}
    local_by_key = {}
    projected = []
    if broker_orders is not None:
        for order in broker_orders:
            local_ref = _field(order, "order_ref")
            instrument = _exact_text(_field(order, "instrument_id"))
            exchange = _exact_text(_field(order, "exchange_id"))
            remote_ref = _remote_ref(_field(order, "external_order_ref"))
            sys_id = _exact_text(_field(order, "order_sys_id"))
            target = target_by_instrument.get(instrument)
            if (
                instrument is None
                or exchange is None
                or target is None
                or target.exchange != exchange
            ):
                blockers.append("broker_order_route_unobserved:{}".format(local_ref))
            if remote_ref is None:
                blockers.append("broker_order_external_ref_unobserved:{}".format(local_ref))
            key = (
                (remote_ref, instrument, exchange)
                if remote_ref is not None and instrument and exchange
                else None
            )
            if key is not None:
                if key in local_by_key:
                    blockers.append("broker_order_identity_duplicate:{}".format(remote_ref))
                local_by_key[key] = order
            side_value = _field(order, "side")
            side = side_value if side_value in {"BUY", "SELL"} else None
            effect_value = _field(order, "position_effect")
            effect = effect_value if effect_value in {"OPEN", "CLOSE"} else None
            state = _exact_text(_field(order, "status")) or "UNKNOWN"
            remaining = _decimal(_field(order, "remaining_quantity"), nonnegative=True)
            owner_scope = _exact_text(_field(order, "owner_strategy_scope"))
            owner_intent = _exact_text(_field(order, "owner_intent_id", _field(order, "intent_id")))
            local_front = _integer(_field(order, "front_id"), allow_zero=False)
            local_session = _integer(_field(order, "session_id"), allow_zero=False)
            execution_unknown = _field(order, "execution_unknown")
            cancel_pending = _field(order, "cancel_pending")
            execution_unknown = execution_unknown if type(execution_unknown) is bool else None
            cancel_pending = cancel_pending if type(cancel_pending) is bool else None
            if side is None:
                blockers.append("working_order_side_unobserved:{}".format(local_ref))
            if effect is None:
                blockers.append("working_order_effect_unobserved:{}".format(local_ref))
            if remaining is None:
                blockers.append("working_order_quantity_unobserved:{}".format(local_ref))
            if owner_scope is None or owner_intent is None:
                blockers.append("working_order_owner_unobserved:{}".format(local_ref))
            if execution_unknown is not False:
                blockers.append("working_order_execution_state_unobserved:{}".format(local_ref))
            if cancel_pending is not False:
                blockers.append("working_order_cancel_state_unobserved:{}".format(local_ref))
            if local_front is None:
                blockers.append("broker_order_front_unobserved:{}".format(local_ref))
            if local_session is None:
                blockers.append("broker_order_session_unobserved:{}".format(local_ref))
            if state.lower() in {"unknown", "created", "submitted", "accepted"}:
                # Mapped below from the authoritative active CTP row.
                pass
            projected.append(
                FactorExecutionWorkingOrderFacts(
                    target_id=target.target_id if target else None,
                    instrument=instrument or "",
                    exchange=exchange,
                    order_ref=remote_ref or str(local_ref),
                    state=state,
                    side=side,
                    position_effect=effect,
                    remaining_quantity=remaining,
                    owner_strategy_scope=owner_scope,
                    owner_intent_id=owner_intent,
                    execution_unknown=execution_unknown,
                    cancel_pending=cancel_pending,
                    broker_order_ref=local_ref if type(local_ref) is int else None,
                    order_sys_id=sys_id,
                    front_id=local_front,
                    session_id=local_session,
                )
            )

    remote_active = _remote_order_rows(remote_rows, blockers, expected_trading_day=trading_day)
    if remote_active is None or local_by_key is None:
        return tuple(projected)
    for key, row in remote_active.items():
        ref, instrument, exchange = key
        order = local_by_key.get(key)
        if order is None:
            blockers.append("remote_working_order_missing_from_broker:{}".format(ref))
            target = target_by_instrument.get(instrument)
            raw_status = str(row.get("OrderStatus", row.get("order_status", ""))).strip()
            unknown_status = raw_status.lower() == "a"
            if unknown_status:
                blockers.append("remote_working_order_status_unknown:{}".format(ref))
            projected.append(
                FactorExecutionWorkingOrderFacts(
                    target_id=(
                        target.target_id
                        if target is not None and target.exchange == exchange
                        else None
                    ),
                    instrument=instrument,
                    exchange=exchange,
                    order_ref=ref,
                    state="UNKNOWN" if unknown_status else "REMOTE_ONLY",
                    side=_order_side(row.get("Direction", row.get("direction"))),
                    position_effect=_position_effect(
                        row.get("CombOffsetFlag", row.get("OffsetFlag", row.get("offset_flag")))
                    ),
                    remaining_quantity=_decimal(
                        row.get("VolumeTotal", row.get("volume_total")), nonnegative=True
                    ),
                    owner_strategy_scope=None,
                    owner_intent_id=None,
                    execution_unknown=True,
                    cancel_pending=None,
                    broker_order_ref=None,
                    order_sys_id=_remote_ref(row.get("OrderSysID", row.get("order_sys_id"))),
                    front_id=_integer(row.get("FrontID", row.get("front_id")), allow_zero=False),
                    session_id=_integer(
                        row.get("SessionID", row.get("session_id")), allow_zero=False
                    ),
                )
            )
            continue
        remote_sys_id = _remote_ref(row.get("OrderSysID", row.get("order_sys_id")))
        local_sys_id = _remote_ref(_field(order, "order_sys_id"))
        if remote_sys_id is not None and remote_sys_id != local_sys_id:
            blockers.append("remote_broker_order_sys_id_mismatch:{}".format(ref))
        remote_front = _integer(row.get("FrontID", row.get("front_id")))
        remote_session = _integer(row.get("SessionID", row.get("session_id")))
        local_front = _integer(_field(order, "front_id"), allow_zero=False)
        local_session = _integer(_field(order, "session_id"), allow_zero=False)
        if remote_front is None or local_front is None:
            blockers.append("remote_broker_order_front_unobserved:{}".format(ref))
        elif remote_front != local_front:
            blockers.append("remote_broker_order_front_mismatch:{}".format(ref))
        if remote_session is None or local_session is None:
            blockers.append("remote_broker_order_session_unobserved:{}".format(ref))
        elif remote_session != local_session:
            blockers.append("remote_broker_order_session_mismatch:{}".format(ref))
        remote_side = _order_side(row.get("Direction", row.get("direction")))
        remote_effect = _position_effect(
            row.get("CombOffsetFlag", row.get("OffsetFlag", row.get("offset_flag")))
        )
        remote_remaining = _decimal(
            row.get("VolumeTotal", row.get("volume_total")), nonnegative=True
        )
        if remote_side is None or remote_side != _field(order, "side"):
            blockers.append("remote_broker_order_side_mismatch:{}".format(ref))
        if remote_effect is None or remote_effect != _field(order, "position_effect"):
            blockers.append("remote_broker_order_effect_mismatch:{}".format(ref))
        if remote_remaining is None or remote_remaining != _decimal(
            _field(order, "remaining_quantity"), nonnegative=True
        ):
            blockers.append("remote_broker_order_quantity_mismatch:{}".format(ref))
        status = row.get("OrderStatus", row.get("order_status"))
        status_text = str(status).strip().lower()
        if status_text == "a":
            blockers.append("remote_working_order_status_unknown:{}".format(ref))
        state = "UNKNOWN" if status_text == "a" else "PARTIAL" if status_text == "1" else "ACCEPTED"
        for index, item in enumerate(projected):
            if (
                item.order_ref == ref
                and item.instrument == instrument
                and item.exchange == exchange
            ):
                projected[index] = FactorExecutionWorkingOrderFacts(
                    target_id=item.target_id,
                    instrument=item.instrument,
                    exchange=item.exchange,
                    order_ref=item.order_ref,
                    state=state,
                    side=item.side,
                    position_effect=item.position_effect,
                    remaining_quantity=item.remaining_quantity,
                    owner_strategy_scope=item.owner_strategy_scope,
                    owner_intent_id=item.owner_intent_id,
                    execution_unknown=item.execution_unknown,
                    cancel_pending=item.cancel_pending,
                    broker_order_ref=item.broker_order_ref,
                    order_sys_id=item.order_sys_id,
                    front_id=local_front,
                    session_id=local_session,
                )
                break
    for key in local_by_key:
        if key not in remote_active:
            blockers.append("broker_working_order_not_remote_active:{}".format(key[0]))

    if intent_records is not None:
        active_local_intents = {
            item.owner_intent_id for item in projected if item.owner_intent_id is not None
        }
        for record in intent_records:
            intent_id = _exact_text(_field(record, "intent_id"))
            state_value = _field(record, "state", _field(record, "status"))
            state = _exact_text(state_value)
            if intent_id is None or state is None:
                blockers.append("journal_intent_identity_unobserved")
                continue
            normalized = state.upper()
            if normalized in {"PREPARED", "DISPATCHING", "UNKNOWN", "CANCEL_PENDING"}:
                blockers.append("journal_intent_unresolved:{}:{}".format(normalized, intent_id))
            elif normalized == "KNOWN" and intent_id not in active_local_intents:
                blockers.append("journal_known_intent_not_joined:{}".format(intent_id))
            elif normalized not in {"KNOWN"}:
                blockers.append("journal_intent_state_unrecognized:{}".format(normalized))
    return tuple(sorted(projected, key=lambda item: (item.instrument, item.order_ref)))


def _snapshot_identifier(
    query_facts: Mapping[str, FactorExecutionQueryFact],
    targets: Tuple[FactorExecutionTarget, ...],
    query_set_id: str,
    valid_margin_target_ids: Tuple[str, ...] = (),
) -> str:
    bindings = [
        ("query_set", query_set_id),
        *((family, query_facts[family].request_id) for family in _BASE_FAMILIES),
    ]
    for target in targets:
        if target.target_id in valid_margin_target_ids:
            fact = query_facts["margin:{}".format(target.target_id)]
            bindings.append(("margin", target.target_id, fact.request_id))
    base = query_facts["account_result"]
    binding_digest = hashlib.sha256(
        json.dumps(bindings, ensure_ascii=True, separators=(",", ":")).encode("ascii")
    ).hexdigest()
    return "ctp.g{}.d{}.q{}".format(
        base.connection_generation,
        base.trading_day,
        binding_digest,
    )


def _risk_totals(
    positions: Tuple[FactorExecutionPositionFacts, ...],
    instruments: Tuple[FactorExecutionInstrumentFacts, ...],
    quotes: Tuple[FactorExecutionQuoteFacts, ...],
    working_orders: Tuple[FactorExecutionWorkingOrderFacts, ...],
    blockers: List[str],
):
    position_order_blocker_prefixes = (
        "external_",
        "position_",
        "broker_position",
        "opposing_",
        "broker_ctp_position",
        "remote_",
        "broker_order",
        "broker_working_order",
        "working_order_",
        "journal_",
        "ctp_reconciliation_",
        "factor_execution_coordinator_",
        "position_book_",
        "open_order_",
    )
    if working_orders or any(code.startswith(position_order_blocker_prefixes) for code in blockers):
        blockers.append("open_order_risk_capacity_unobserved")
        return None, None
    instruments_by_target = {item.target_id: item for item in instruments}
    quotes_by_instrument = {item.instrument: item for item in quotes}
    notional = Decimal(0)
    worst_loss = Decimal(0)
    for position in positions:
        if position.target_id is None or position.quantity is None:
            return None, None
        if position.quantity == 0:
            continue
        risk = instruments_by_target.get(position.target_id)
        quote = quotes_by_instrument.get(position.instrument)
        if (
            risk is None
            or quote is None
            or risk.multiplier is None
            or quote.quality != "GOOD"
            or quote.bid is None
            or quote.ask is None
            or position.average_price is None
            or position.stop_price is None
        ):
            return None, None
        mark = max(quote.bid, quote.ask)
        notional += abs(Decimal(position.quantity)) * risk.multiplier * mark
        if position.quantity > 0:
            distance = position.average_price - position.stop_price
        else:
            distance = position.stop_price - position.average_price
        if distance < 0:
            blockers.append("position_stop_side_invalid:{}".format(position.instrument))
            return None, None
        worst_loss += abs(Decimal(position.quantity)) * risk.multiplier * distance
    return notional, worst_loss


def _dated_text_tuple(value: Any) -> Tuple[str, ...]:
    if not isinstance(value, (tuple, list)):
        return ()
    return tuple(item for item in value if type(item) is str and item and item == item.strip())


def _dated_lot_fact(value: Any) -> FactorExecutionDatedCloseLotFacts:
    return FactorExecutionDatedCloseLotFacts(
        execution_id=_exact_text(_field(value, "execution_id")),
        intent_id=_exact_text(_field(value, "intent_id")),
        owner_intent_id=_exact_text(_field(value, "owner_intent_id")),
        strategy_scope=_exact_text(_field(value, "strategy_scope")),
        trading_day=_exact_text(_field(value, "trading_day")),
        position_side=_exact_text(_field(value, "position_side")),
        hedge_flag=_ctp_single_char(_field(value, "hedge_flag")),
        opened_quantity=_decimal(_field(value, "opened_quantity"), nonnegative=True),
        closed_quantity=_decimal(_field(value, "closed_quantity"), nonnegative=True),
        remaining_quantity=_decimal(_field(value, "remaining_quantity"), nonnegative=True),
        open_observation_id=_exact_text(_field(value, "open_observation_id")),
        open_snapshot_id=_exact_text(_field(value, "open_snapshot_id")),
        open_query_set_id=_exact_text(_field(value, "open_query_set_id")),
        close_execution_ids=_dated_text_tuple(_field(value, "close_execution_ids", ())),
    )


def _dated_close_legs(
    coordinator: Any,
    facts: FactorExecutionFacts,
    targets: Tuple[FactorExecutionTarget, ...],
    blockers: List[str],
) -> Tuple[FactorExecutionDatedCloseLegFacts, ...]:
    """Project Book-owned dated lots into explicit close offset facts."""

    method = getattr(_field(coordinator, "position_book"), "dated_snapshot", None)
    projected = []
    positions_by_target = {
        position.target_id: position
        for position in facts.positions
        if position.target_id is not None
    }
    for target in targets:
        if target.exchange.upper() not in {"SHFE", "INE"}:
            continue
        position = positions_by_target.get(target.target_id)
        if position is None or position.quantity is None or position.quantity == 0:
            continue
        if (
            position.position_book_status == "FOREIGN_OWNER"
            and position.position_book_blocker_code == "POSITION_OWNED_BY_OTHER_STRATEGY"
        ):
            # This strategy has no authority to close another strategy's lots.
            # Keep the foreign-owner blocker and validate raw CTP inventory in
            # the read-only facts path; do not request owner-scoped close legs.
            continue
        if not callable(method):
            blocker = "dated_position_book_projection_unavailable:{}".format(target.target_id)
            blockers.append(blocker)
            continue
        try:
            proof = method(facts, target_id=target.target_id)
        except Exception as exc:
            blocker = "dated_position_book_projection_failed:{}:{}".format(
                target.target_id, type(exc).__name__
            )
            blockers.append(blocker)
            continue

        expected_day = facts.account.trading_day if facts.account is not None else None
        expected_generation = (
            facts.account.connection_generation if facts.account is not None else None
        )
        expected_account = facts.account.account_fingerprint if facts.account is not None else None
        identity_ok = bool(
            _field(proof, "account_scope") == facts.account_scope
            and _field(proof, "strategy_scope") == facts.strategy_scope
            and _field(proof, "target_id") == target.target_id
            and _field(proof, "instrument") == target.instrument
            and _field(proof, "exchange") == target.exchange
            and _field(proof, "query_set_id") == facts.query_set_id
            and _field(proof, "account_fingerprint") == expected_account
            and _field(proof, "connection_generation") == expected_generation
            and _field(proof, "trading_day") == expected_day
            and _field(proof, "snapshot_id") == facts.snapshot_id
            and _aware_utc(_field(proof, "available_at")) == facts.available_at
        )
        proof_ready = bool(
            identity_ok
            and _field(proof, "status") == "MATCHED"
            and _field(proof, "ready") is True
            and not tuple(_field(proof, "blockers", ()) or ())
        )
        if not identity_ok:
            blockers.append("dated_position_proof_binding_mismatch:{}".format(target.target_id))

        raw_rows = tuple(position.dated_inventory_rows)
        raw_rows_by_id = {
            row.source_row_id: row for row in raw_rows if row.source_row_id is not None
        }
        proof_row_ids = set(_dated_text_tuple(_field(proof, "source_row_ids", ())))
        route_row_ids = set(raw_rows_by_id)
        if proof_row_ids != route_row_ids:
            proof_ready = False
            blockers.append("dated_position_source_rows_incomplete:{}".format(target.target_id))

        buckets = _field(proof, "buckets", ())
        if not isinstance(buckets, (tuple, list)):
            buckets = ()
        active_orders = tuple(
            order
            for order in facts.working_orders
            if order.instrument == target.instrument and order.exchange == target.exchange
        )
        order_blockers = ()
        if active_orders:
            order_blockers = ("DATED_TARGET_HAS_WORKING_ORDER",)

        if not buckets:
            proof_ready = False
            blockers.append("dated_position_buckets_unobserved:{}".format(target.target_id))

        for bucket in buckets:
            side = _exact_text(_field(bucket, "position_side"))
            hedge = _ctp_single_char(_field(bucket, "hedge_flag"))
            date = _exact_text(_field(bucket, "position_date"))
            offset_flag = {"TODAY": "3", "HISTORY": "4"}.get(date)
            offset = {"TODAY": "close_today", "HISTORY": "close_yesterday"}.get(date)
            order_side = {"LONG": "SELL", "SHORT": "BUY"}.get(side)
            source_ids = _dated_text_tuple(_field(bucket, "source_row_ids", ()))
            bucket_rows = tuple(
                raw_rows_by_id[row_id] for row_id in source_ids if row_id in raw_rows_by_id
            )
            provider_quantity = _decimal(_field(bucket, "provider_quantity"), nonnegative=True)
            owned_quantity = _decimal(_field(bucket, "owned_quantity"), nonnegative=True)
            available_quantity = _decimal(_field(bucket, "available_quantity"), nonnegative=True)
            owner_scope = _exact_text(_field(bucket, "owner_strategy_scope"))
            owner_intent = _exact_text(_field(bucket, "owner_intent_id"))
            opening_ids = _dated_text_tuple(_field(bucket, "opening_execution_ids", ()))
            closing_ids = _dated_text_tuple(_field(bucket, "close_execution_ids", ()))
            lots_source = _field(bucket, "lots", ())
            lots = (
                tuple(_dated_lot_fact(item) for item in lots_source)
                if isinstance(lots_source, (tuple, list))
                else ()
            )
            bucket_blockers = list(_dated_text_tuple(_field(bucket, "blockers", ())))
            bucket_blockers.extend(order_blockers)
            bucket_blockers.extend(blocker for row in bucket_rows for blocker in row.blockers)
            if len(bucket_rows) != len(source_ids):
                bucket_blockers.append("DATED_BUCKET_SOURCE_ROW_UNRESOLVED")
            if not bucket_rows:
                bucket_blockers.append("DATED_BUCKET_SOURCE_ROWS_UNOBSERVED")
            if any(
                row.position_side != side
                or row.hedge_flag != hedge
                or row.position_date != date
                or row.position is None
                or row.trading_day != expected_day
                or row.query_set_id != facts.query_set_id
                or row.snapshot_id != facts.snapshot_id
                or row.source_row_id not in source_ids
                for row in bucket_rows
            ):
                bucket_blockers.append("DATED_BUCKET_SOURCE_IDENTITY_MISMATCH")
            source_quantity = (
                sum((row.position for row in bucket_rows), Decimal(0))
                if bucket_rows and all(row.position is not None for row in bucket_rows)
                else None
            )
            if source_quantity is None or source_quantity != provider_quantity:
                bucket_blockers.append("DATED_BUCKET_PROVIDER_QUANTITY_MISMATCH")
            if any(
                value != Decimal(0)
                for row in bucket_rows
                for value in (
                    row.long_frozen,
                    row.short_frozen,
                    row.comb_long_frozen,
                    row.comb_short_frozen,
                    row.strike_frozen,
                    row.abandon_frozen,
                    row.long_frozen_amount,
                    row.short_frozen_amount,
                    row.frozen_margin,
                    row.frozen_cash,
                    row.frozen_commission,
                    row.strike_frozen_amount,
                    row.yd_strike_frozen,
                )
            ):
                bucket_blockers.append("DATED_BUCKET_FREEZE_PRESENT")
            if any(
                value is None
                for row in bucket_rows
                for value in (
                    row.long_frozen,
                    row.short_frozen,
                    row.comb_long_frozen,
                    row.comb_short_frozen,
                    row.strike_frozen,
                    row.abandon_frozen,
                    row.long_frozen_amount,
                    row.short_frozen_amount,
                    row.frozen_margin,
                    row.frozen_cash,
                    row.frozen_commission,
                    row.strike_frozen_amount,
                    row.yd_strike_frozen,
                )
            ):
                bucket_blockers.append("DATED_BUCKET_FREEZE_UNOBSERVED")
            if (
                owner_scope != facts.strategy_scope
                or owner_intent is None
                or owner_intent != position.owner_intent_id
            ):
                bucket_blockers.append("DATED_BUCKET_OWNER_MISMATCH")
            if not opening_ids or not lots:
                bucket_blockers.append("DATED_BUCKET_OPENING_LOTS_UNOBSERVED")
            if (
                provider_quantity is None
                or owned_quantity != provider_quantity
                or available_quantity != provider_quantity
                or provider_quantity <= 0
                or provider_quantity != provider_quantity.to_integral_value()
            ):
                bucket_blockers.append("DATED_BUCKET_QUANTITY_UNAVAILABLE")
            if facts.risk_reduction_blockers:
                bucket_blockers.append("DATED_GLOBAL_RISK_EVIDENCE_BLOCKED")

            leg_blockers = tuple(sorted(set(bucket_blockers)))
            ready = bool(
                proof_ready
                and _field(bucket, "ready") is True
                and not leg_blockers
                and side in {"LONG", "SHORT"}
                and date in {"TODAY", "HISTORY"}
                and offset_flag is not None
                and offset is not None
                and order_side is not None
                and hedge in {"1", "2", "3", "5"}
                and provider_quantity is not None
                and owned_quantity is not None
                and available_quantity is not None
                and owner_scope is not None
                and owner_intent is not None
                and facts.query_set_id is not None
                and expected_account is not None
                and expected_generation is not None
                and expected_day is not None
                and facts.snapshot_id is not None
                and facts.available_at is not None
            )
            if not ready:
                blockers.append(
                    "dated_close_leg_unavailable:{}:{}:{}:{}".format(
                        target.target_id, side or "unknown", hedge or "unknown", date or "unknown"
                    )
                )
            projected.append(
                FactorExecutionDatedCloseLegFacts(
                    target_id=target.target_id,
                    instrument=target.instrument,
                    exchange=target.exchange,
                    position_side=side,
                    hedge_flag=hedge,
                    position_date=date,
                    offset_flag=offset_flag,
                    offset=offset,
                    side=order_side,
                    provider_quantity=provider_quantity,
                    owned_quantity=owned_quantity,
                    available_quantity=available_quantity,
                    owner_strategy_scope=owner_scope,
                    owner_intent_id=owner_intent,
                    query_set_id=_exact_text(_field(proof, "query_set_id")),
                    account_fingerprint=_exact_text(_field(proof, "account_fingerprint")),
                    connection_generation=_integer(_field(proof, "connection_generation")),
                    trading_day=_exact_text(_field(proof, "trading_day")),
                    snapshot_id=_exact_text(_field(proof, "snapshot_id")),
                    available_at=_aware_utc(_field(proof, "available_at")),
                    source_row_ids=source_ids,
                    opening_execution_ids=opening_ids,
                    close_execution_ids=closing_ids,
                    lots=lots,
                    inventory_rows=bucket_rows,
                    ready=ready,
                    blockers=leg_blockers,
                )
            )
    return tuple(projected)


def project_factor_execution_facts(
    store: RegisteredSimStore,
    broker: Any,
    *,
    targets: Tuple[FactorExecutionTarget, ...],
    account_scope: str,
    strategy_scope: str,
    now: datetime,
    quote_max_age: timedelta,
    max_query_age: timedelta,
    query_set: Optional[FactorExecutionQuerySetFacts] = None,
    execution_target_ids: Optional[Tuple[str, ...]] = None,
) -> FactorExecutionFacts:
    """Project cached live facts without running any SDK query.

    ``now`` is the caller's single decision-clock observation. The projection
    never substitutes wall-clock or query-completion time for it, so future
    evidence remains blocked until the caller's clock reaches that evidence.
    """

    if not isinstance(store, RegisteredSimStore):
        raise TypeError("store must be a RegisteredSimStore")
    if getattr(broker, "store", None) is not store:
        raise ValueError("broker must be bound to the exact RegisteredSimStore")
    if (
        type(account_scope) is not str
        or not account_scope
        or account_scope != account_scope.strip()
    ):
        raise ValueError("account_scope must be exact non-empty text")
    if (
        type(strategy_scope) is not str
        or not strategy_scope
        or strategy_scope != strategy_scope.strip()
    ):
        raise ValueError("strategy_scope must be exact non-empty text")
    now_utc = _aware_utc(now)
    if now_utc is None:
        raise ValueError("now must be timezone-aware")
    for name, value in (("quote_max_age", quote_max_age), ("max_query_age", max_query_age)):
        if not isinstance(value, timedelta) or value <= timedelta(0):
            raise ValueError("{} must be a positive timedelta".format(name))
    bound_targets = _valid_targets(tuple(targets))
    full_target_ids = tuple(target.target_id for target in bound_targets)
    if execution_target_ids is None:
        bound_execution_target_ids = full_target_ids
    else:
        if (
            type(execution_target_ids) is not tuple
            or not execution_target_ids
            or any(
                type(target_id) is not str or not target_id or target_id != target_id.strip()
                for target_id in execution_target_ids
            )
            or len(set(execution_target_ids)) != len(execution_target_ids)
            or not set(execution_target_ids).issubset(set(full_target_ids))
        ):
            raise ValueError("execution_target_ids must be a non-empty immutable target subset")
        requested_execution_target_ids = set(execution_target_ids)
        bound_execution_target_ids = tuple(
            target_id
            for target_id in full_target_ids
            if target_id in requested_execution_target_ids
        )

    blockers: List[str] = []
    diagnostics: List[str] = []
    query_results = {}
    query_facts = {}
    provenance = []
    query_getter = getattr(store, "get_registered_sim_query_snapshot", None)
    if not callable(query_getter):
        blockers.append("query_snapshot_getter_unavailable")
    for family in _BASE_FAMILIES:
        try:
            result = query_getter(family) if callable(query_getter) else None
        except Exception as exc:
            result = None
            blockers.append("query_snapshot_read_failed:{}:{}".format(family, type(exc).__name__))
        query_results[family] = result
        fact = _query_fact(family, result) if result is not None else _missing_query_fact(family)
        query_facts[family] = fact
        provenance.append(fact)
        if result is None:
            blockers.append("query_snapshot_unavailable:{}".format(family))
        elif not _query_valid(
            family,
            result,
            now=now_utc,
            max_age=max_query_age,
            require_full_scope=True,
        ):
            blockers.append("query_snapshot_invalid_or_stale:{}".format(family))

    margin_results = {}
    for target in bound_targets:
        filters = {
            "instrument_id": target.instrument,
            "exchange_id": target.exchange,
            "hedge_flag": "1",
        }
        try:
            result = (
                query_getter("instrument_margin_rate_result", **filters)
                if callable(query_getter)
                else None
            )
        except Exception as exc:
            result = None
            blockers.append(
                "query_snapshot_read_failed:instrument_margin_rate_result:{}:{}".format(
                    target.target_id, type(exc).__name__
                )
            )
        margin_results[target.target_id] = result
        fact = (
            _query_fact("instrument_margin_rate_result", result, target_id=target.target_id)
            if result is not None
            else _missing_query_fact("instrument_margin_rate_result", target.target_id)
        )
        query_facts["margin:{}".format(target.target_id)] = fact
        provenance.append(fact)
        if result is None:
            blockers.append(
                "query_failed:instrument_margin_rate_result:{}:unavailable".format(target.target_id)
            )
        elif not _query_valid(
            "instrument_margin_rate_result",
            result,
            now=now_utc,
            max_age=max_query_age,
            require_full_scope=False,
            expected_filters=filters,
        ):
            blockers.append(
                "query_facts_invalid:instrument_margin_rate_result:{}".format(target.target_id)
            )

    current_queries = False
    try:
        current_queries = store.supports_complete_ctp_queries(include_reference_data=True) is True
    except Exception as exc:
        blockers.append("query_session_check_failed:{}".format(type(exc).__name__))
    if not current_queries:
        blockers.append("complete_query_set_not_current")

    base_facts = [query_facts[family] for family in _BASE_FAMILIES]
    base_results = [query_results[family] for family in _BASE_FAMILIES]
    query_set_valid = bool(
        current_queries
        and all(
            _query_valid(
                family,
                query_results[family],
                now=now_utc,
                max_age=max_query_age,
                require_full_scope=True,
            )
            for family in _BASE_FAMILIES
        )
    )
    if query_set is None:
        query_set_valid = False
        blockers.append("completed_query_set_receipt_unavailable")
    elif not _query_set_matches(
        query_set,
        tuple(query_facts[family] for family in _BASE_FAMILIES),
        now=now_utc,
        max_age=max_query_age,
    ):
        query_set_valid = False
        blockers.append("completed_query_set_receipt_mismatch")
    base_identity = None
    if query_set_valid:
        generations = {fact.connection_generation for fact in base_facts}
        days = {fact.trading_day for fact in base_facts}
        accounts = {_exact_text(_field(result, "account_fingerprint")) for result in base_results}
        request_ids = {fact.request_id for fact in base_facts}
        if (
            len(generations) != 1
            or len(days) != 1
            or len(accounts) != 1
            or None in accounts
            or len(request_ids) != len(_BASE_FAMILIES)
        ):
            query_set_valid = False
            blockers.append("query_identity_set_mismatch")
        else:
            base_identity = (next(iter(generations)), next(iter(days)), next(iter(accounts)))

    valid_margin_results = {}
    for target in bound_targets:
        result = margin_results[target.target_id]
        fact = query_facts["margin:{}".format(target.target_id)]
        if result is None or base_identity is None:
            valid_margin_results[target.target_id] = None
            continue
        if (
            fact.connection_generation != base_identity[0]
            or fact.trading_day != base_identity[1]
            or _exact_text(_field(result, "account_fingerprint")) != base_identity[2]
        ):
            blockers.append("margin_query_identity_mismatch:{}".format(target.target_id))
            valid_margin_results[target.target_id] = None
            continue
        if not _query_valid(
            "instrument_margin_rate_result",
            result,
            now=now_utc,
            max_age=max_query_age,
            require_full_scope=False,
            expected_filters={
                "instrument_id": target.instrument,
                "exchange_id": target.exchange,
                "hedge_flag": "1",
            },
        ):
            valid_margin_results[target.target_id] = None
            continue
        valid_margin_results[target.target_id] = result

    if not query_set_valid:
        snapshot_id = None
        available_at = None
        account = None
        return FactorExecutionFacts(
            account_scope=account_scope,
            strategy_scope=strategy_scope,
            snapshot_id=snapshot_id,
            available_at=available_at,
            account=account,
            positions=(),
            working_orders=(),
            terminal_orders=(),
            trade_observations=(),
            quotes=(),
            instruments=(),
            route_eligibilities=(),
            query_provenance=tuple(provenance),
            blockers=tuple(sorted(set(blockers))),
            target_ids=full_target_ids,
            execution_target_ids=bound_execution_target_ids,
        )

    assert query_set is not None

    completed = [fact.completed_at for fact in base_facts]
    if any(value is None for value in completed):
        blockers.append("query_completion_time_unobserved")
        available_at = None
    else:
        available_at = max(completed)
    if available_at is None:
        snapshot_id = None
        account = None
        return FactorExecutionFacts(
            account_scope=account_scope,
            strategy_scope=strategy_scope,
            snapshot_id=snapshot_id,
            available_at=available_at,
            account=account,
            positions=(),
            working_orders=(),
            terminal_orders=(),
            trade_observations=(),
            quotes=(),
            instruments=(),
            route_eligibilities=(),
            query_provenance=tuple(provenance),
            blockers=tuple(sorted(set(blockers))),
            target_ids=full_target_ids,
            execution_target_ids=bound_execution_target_ids,
        )
    valid_margin_target_ids = tuple(
        target.target_id
        for target in bound_targets
        if valid_margin_results[target.target_id] is not None
    )
    snapshot_id = _snapshot_identifier(
        query_facts, bound_targets, query_set.query_set_id, valid_margin_target_ids
    )

    # Every query is bound to the same account/generation/day. A margin miss is
    # capital-only; the complete unfiltered account/position/order/trade/contract
    # set remains available for conservative reductions.
    generation, trading_day, account_fingerprint = base_identity
    try:
        health = store.get_ctp_query_health()
    except Exception as exc:
        health = None
        blockers.append("ctp_query_health_unavailable:{}".format(type(exc).__name__))
    health_complete = bool(
        isinstance(health, Mapping)
        and health.get("evidence_complete") is True
        and type(health.get("unknown_intent_count")) is int
        and health.get("unknown_intent_count") == 0
        and type(health.get("unmatched_trade_count")) is int
        and health.get("unmatched_trade_count") >= 0
    )
    if not health_complete:
        blockers.append("ctp_reconciliation_health_blocked")
    health_clear = bool(health_complete and health.get("unmatched_trade_count") == 0)

    route_facts = tuple(
        _route_fact(store, target, query_identity=base_identity, blockers=blockers)
        for target in bound_targets
    )
    route_flags = tuple(item.eligible for item in route_facts)
    route_permitted = (
        True
        if route_flags and all(flag is True for flag in route_flags)
        else False
        if any(flag is False for flag in route_flags)
        else None
    )
    available_margin, used_margin = _account_values(
        _field(query_results["account_result"], "rows"), blockers
    )
    account = FactorExecutionAccountFacts(
        account_scope=account_scope,
        snapshot_id=snapshot_id,
        available_at=available_at,
        route_permitted=route_permitted,
        available_margin=available_margin,
        used_margin=used_margin,
        current_notional=None,
        current_worst_case_loss=None,
        account_fingerprint=account_fingerprint,
        connection_generation=generation,
        trading_day=trading_day,
    )

    remote_positions = _position_rows(_field(query_results["positions_result"], "rows"), blockers)
    dated_inventory_rows = _position_dated_inventory_rows(
        _field(query_results["positions_result"], "rows"),
        query_fact=query_facts["positions_result"],
        query_set_id=query_set.query_set_id,
        snapshot_id=snapshot_id,
        available_at=available_at,
        blockers=blockers,
    )
    dated_inventory_by_route = defaultdict(list)
    for row in dated_inventory_rows:
        dated_inventory_by_route[(row.instrument, row.exchange)].append(row)
    coordinator = getattr(broker, "factor_execution_coordinator", None)
    if coordinator is None:
        blockers.append("factor_execution_coordinator_unavailable")
    positions = _position_facts(
        broker,
        bound_targets,
        remote_positions,
        coordinator=coordinator,
        account_scope=account_scope,
        strategy_scope=strategy_scope,
        snapshot_id=snapshot_id,
        available_at=available_at,
        dated_inventory_by_route=dated_inventory_by_route,
        blockers=blockers,
    )

    instruments = []
    margin_rates_by_target = {}
    for target in bound_targets:
        row = _instrument_row(
            _field(query_results["instruments_result"], "rows"),
            target.instrument,
            target.exchange,
            blockers,
        )
        margin_result = valid_margin_results[target.target_id]
        multiplier = _tick_size = _lower = _upper = None
        trading = None
        if row is not None:
            multiplier = _decimal(
                row.get("VolumeMultiple", row.get("volume_multiple")), positive=True
            )
            _tick_size = _decimal(row.get("PriceTick", row.get("price_tick")), positive=True)
            _lower = _decimal(row.get("LowerLimitPrice", row.get("lower_limit_price")))
            _upper = _decimal(row.get("UpperLimitPrice", row.get("upper_limit_price")))
            trading = _bool_fact(row.get("IsTrading", row.get("is_trading")))
            if multiplier is None:
                blockers.append("instrument_multiplier_unobserved:{}".format(target.instrument))
            if _tick_size is None:
                blockers.append("instrument_tick_unobserved:{}".format(target.instrument))
            if _lower is None or _upper is None or _lower >= _upper:
                blockers.append("instrument_limits_unobserved:{}".format(target.instrument))
            if trading is None:
                blockers.append("instrument_tradability_unobserved:{}".format(target.instrument))
            elif not trading:
                blockers.append("instrument_not_trading:{}".format(target.instrument))
        margin_rates_by_target[target.target_id] = (
            _margin_rates(
                _field(margin_result, "rows"), target.instrument, target.exchange, blockers
            )
            if margin_result is not None
            else None
        )
        instruments.append(
            FactorExecutionInstrumentFacts(
                target_id=target.target_id,
                instrument=target.instrument,
                exchange=target.exchange,
                snapshot_id=snapshot_id,
                available_at=max(
                    value
                    for value in (
                        query_facts["instruments_result"].completed_at,
                        query_facts["margin:{}".format(target.target_id)].completed_at
                        if margin_result is not None
                        else None,
                    )
                    if value is not None
                ),
                trading_permitted=trading,
                multiplier=multiplier,
                long_margin_per_hand=None,
                short_margin_per_hand=None,
                tick_size=_tick_size,
                lower_limit=_lower,
                upper_limit=_upper,
            )
        )

    instrument_by_target = {
        target.target_id: instrument for target, instrument in zip(bound_targets, instruments)
    }
    quotes = tuple(
        _quote_fact(
            store,
            target,
            instrument_fact=instrument_by_target[target.target_id],
            snapshot_id=snapshot_id,
            generation=generation,
            trading_day=trading_day,
            available_at=available_at,
            now=now_utc,
            max_age=quote_max_age,
            blockers=blockers,
        )
        for target in bound_targets
    )
    quote_by_target = {target.target_id: quote for target, quote in zip(bound_targets, quotes)}
    instruments_with_margin = []
    for target, instrument in zip(bound_targets, instruments):
        rates = margin_rates_by_target[target.target_id]
        quote = quote_by_target[target.target_id]
        long_margin = short_margin = None
        if (
            rates is not None
            and instrument.multiplier is not None
            and quote.quality == "GOOD"
            and quote.bid is not None
            and quote.ask is not None
        ):
            long_money, long_volume, short_money, short_volume = rates
            # CTP money ratio applies to notional; volume ratio is per hand.
            long_margin = quote.ask * instrument.multiplier * long_money + long_volume
            short_margin = quote.bid * instrument.multiplier * short_money + short_volume
            if long_margin <= 0:
                long_margin = None
            if short_margin <= 0:
                short_margin = None
        if long_margin is None:
            blockers.append("long_margin_per_hand_unobserved:{}".format(target.target_id))
        if short_margin is None:
            blockers.append("short_margin_per_hand_unobserved:{}".format(target.target_id))
        instruments_with_margin.append(
            FactorExecutionInstrumentFacts(
                target_id=instrument.target_id,
                instrument=instrument.instrument,
                exchange=instrument.exchange,
                snapshot_id=instrument.snapshot_id,
                available_at=instrument.available_at,
                trading_permitted=instrument.trading_permitted,
                multiplier=instrument.multiplier,
                long_margin_per_hand=long_margin,
                short_margin_per_hand=short_margin,
                tick_size=instrument.tick_size,
                lower_limit=instrument.lower_limit,
                upper_limit=instrument.upper_limit,
                stop_loss_ticks=None,
                max_hands=None,
            )
        )
    instruments = tuple(instruments_with_margin)

    orders = _orders_facts(
        broker,
        bound_targets,
        _field(query_results["orders_result"], "rows"),
        coordinator=coordinator,
        trading_day=trading_day,
        blockers=blockers,
    )
    terminal_orders = _terminal_order_facts(
        _field(query_results["orders_result"], "rows"),
        query_fact=query_facts["orders_result"],
        snapshot_id=snapshot_id,
        blockers=blockers,
    )
    trade_observations = _trade_observation_facts(
        _field(query_results["trades_result"], "rows"),
        query_fact=query_facts["trades_result"],
        snapshot_id=snapshot_id,
        blockers=blockers,
    )
    unmatched_trade_count = health.get("unmatched_trade_count") if health_complete else None
    diagnostics.extend(
        _unmatched_trade_diagnostic(
            health_count=unmatched_trade_count,
            trade_rows=_field(query_results["trades_result"], "rows"),
            order_rows=_field(query_results["orders_result"], "rows"),
            observations=trade_observations,
            blockers=blockers,
        )
    )
    position_order_blocker_prefixes = (
        "external_",
        "position_",
        "broker_position",
        "opposing_",
        "broker_ctp_position",
        "remote_",
        "broker_order",
        "broker_working_order",
        "working_order_",
        "journal_",
        "ctp_reconciliation_",
        "factor_execution_coordinator_",
        "position_book_",
        "open_order_",
    )
    position_order_evidence_clear = not any(
        code.startswith(position_order_blocker_prefixes) for code in blockers
    )
    all_flat = bool(
        health_clear
        and position_order_evidence_clear
        and remote_positions is not None
        and all(sides["LONG"] == 0 and sides["SHORT"] == 0 for sides in remote_positions.values())
        and all(position.quantity == 0 for position in positions)
        and len(positions) == len(bound_targets)
        and not any(position.target_id is None for position in positions)
        and not orders
    )
    if all_flat:
        current_notional = Decimal(0)
        worst_case_loss = Decimal(0)
    else:
        current_notional, worst_case_loss = _risk_totals(
            positions, instruments, quotes, orders, blockers
        )
    if current_notional is None:
        blockers.append("current_notional_unobserved")
    if worst_case_loss is None:
        blockers.append("current_worst_case_loss_unobserved")
    account = FactorExecutionAccountFacts(
        account_scope=account.account_scope,
        snapshot_id=account.snapshot_id,
        available_at=account.available_at,
        route_permitted=account.route_permitted,
        available_margin=account.available_margin,
        used_margin=account.used_margin,
        current_notional=current_notional,
        current_worst_case_loss=worst_case_loss,
        account_fingerprint=account.account_fingerprint,
        connection_generation=account.connection_generation,
        trading_day=account.trading_day,
    )
    facts = FactorExecutionFacts(
        account_scope=account_scope,
        strategy_scope=strategy_scope,
        snapshot_id=snapshot_id,
        available_at=available_at,
        account=account,
        positions=positions,
        working_orders=orders,
        terminal_orders=terminal_orders,
        trade_observations=trade_observations,
        quotes=quotes,
        instruments=instruments,
        route_eligibilities=route_facts,
        query_provenance=tuple(provenance),
        blockers=tuple(sorted(set(blockers))),
        diagnostics=tuple(sorted(set(diagnostics))),
        query_set_id=query_set.query_set_id,
        target_ids=full_target_ids,
        execution_target_ids=bound_execution_target_ids,
    )
    trade_blockers = _trade_reconciliation_blockers(coordinator, facts)
    terminal_blockers = _terminal_order_reconciliation_blockers(coordinator, facts)
    if trade_blockers or terminal_blockers:
        facts = replace(
            facts,
            blockers=tuple(sorted(set(facts.blockers + trade_blockers + terminal_blockers))),
        )
    dated_blockers: List[str] = []
    dated_legs = _dated_close_legs(coordinator, facts, bound_targets, dated_blockers)
    if dated_legs or dated_blockers:
        facts = replace(
            facts,
            dated_close_legs=dated_legs,
            blockers=tuple(sorted(set(facts.blockers + tuple(dated_blockers)))),
        )
    scoped_route_permitted = facts._scoped_route_permitted()
    if facts.account.route_permitted is not scoped_route_permitted:
        facts = replace(
            facts,
            account=replace(facts.account, route_permitted=scoped_route_permitted),
        )
    return facts


__all__ = [
    "FactorExecutionAccountFacts",
    "FactorExecutionDatedCloseLegFacts",
    "FactorExecutionDatedCloseLotFacts",
    "FactorExecutionDatedInventoryRow",
    "FactorExecutionFacts",
    "FactorExecutionInstrumentFacts",
    "FactorExecutionPositionFacts",
    "FactorExecutionQueryFact",
    "FactorExecutionQuerySetFacts",
    "FactorExecutionQuoteFacts",
    "FactorExecutionRefreshReceipt",
    "FactorExecutionRouteFacts",
    "FactorExecutionTarget",
    "FactorExecutionTerminalOrderFacts",
    "FactorExecutionTradeObservationFacts",
    "FactorExecutionWorkingOrderFacts",
    "project_factor_execution_facts",
    "refresh_factor_execution_queries",
]
