"""Ordinary Alpha003 Strategy, risk planner, and Broker order projection.

The shared factor engine owns calculations. This module projects complete
factor snapshots and authoritative execution facts into ordinary Backtrader
buy/sell/cancel calls; the Broker and Store remain the only execution route.
"""

from __future__ import annotations

import math
import hashlib
import struct
import threading
from collections import deque
from collections.abc import Mapping
from dataclasses import dataclass, replace
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, DecimalException, InvalidOperation, ROUND_CEILING, localcontext
from numbers import Real
from types import MappingProxyType
from typing import Any, FrozenSet, Iterable, Optional, Tuple

import backtrader as bt

from backtrader.research.alpha101 import get_alpha
from backtrader.research.specs import FactorSpec


FACTOR_NAME = "alpha003"
FACTOR_PANEL_LINE = "factor"
DEFAULT_FACTOR_MODE = "native"
DEFAULT_DIRECTION = 1
DEFAULT_REBALANCE_GRIDS = 5
DEFAULT_PREHEAT_BARS = 30
FACTOR_FREQUENCY = "1min"
# The shared CTP facts projector defines this as CloseProfit + PositionProfit
# - Commission, all in the one qualified CNY Account row.
RUN_LOSS_PNL_BASIS = "ctp_total_net_after_fees_v1"
_RUN_LOSS_OPEN_REJECTION_CODES = frozenset(
    {
        "RUN_LOSS_GUARD_NOT_CONFIGURED",
        "RUN_LOSS_GUARD_CONTEXT_MISMATCH",
        "RUN_LOSS_GUARD_POLICY_CONFLICT",
        "RUN_LOSS_GUARD_OBSERVATION_MISMATCH",
        "RUN_LOSS_OBSERVATION_STALE",
        "RUN_LOSS_OBSERVATION_CONFLICT",
        "RUN_LOSS_OBSERVATION_NOT_MONOTONE",
        "RUN_LOSS_GUARD_LATE_ENABLE_AFTER_OPEN",
        "RUN_LOSS_GUARD_ENABLE_SCAN_LIMIT",
        "RUN_TOTAL_NET_LOSS_LIMIT_REACHED",
        "RUN_LOSS_ACCOUNT_FACTS_INVALID",
        "RUN_LOSS_ACCOUNT_SCOPE_MISMATCH",
        "RUN_LOSS_ACCOUNT_PNL_UNQUALIFIED",
        "RUN_LOSS_ACCOUNT_TRADING_DAY_MISMATCH",
        "RUN_LOSS_ACCOUNT_CURRENCY_MISMATCH",
        "RUN_LOSS_ACCOUNT_SNAPSHOT_ID_INVALID",
        "RUN_LOSS_ACCOUNT_ASOF_INVALID",
        "RUN_LOSS_ACCOUNT_REFRESH_INCOMPLETE",
        "RUN_LOSS_ACCOUNT_QUERYSET_MISMATCH",
    }
)
_SOURCE_CONTINUITY_FAILURE_CODES = frozenset(
    {
        "DURABLE_DECISION_COORDINATOR_UNAVAILABLE",
        "SOURCE_RECEIPT_BUILD_FAILED",
        "SOURCE_RECEIPT_WRITE_FAILED",
        "SOURCE_HIGHWATER_CONFIRMATION_FAILED",
    }
)

ProductKey = Tuple[str, str]


@dataclass(frozen=True)
class CohortBatchFacts:
    """Small immutable projection of one complete shared cohort receipt."""

    status: str
    batch_id: str
    cohort_id: str
    calendar_id: str
    epoch_id: int
    close_time: datetime
    available_at: datetime

    def __post_init__(self) -> None:
        for name in ("status", "batch_id", "cohort_id", "calendar_id"):
            _require_text(getattr(self, name), name)
        _require_epoch(self.epoch_id)
        _require_utc_datetime(self.close_time, "cohort close_time")
        _require_utc_datetime(self.available_at, "cohort available_at")


@dataclass(frozen=True)
class FactorPoint:
    """One target's raw Alpha003 output and shared-engine availability facts."""

    target_id: str
    product_key: Optional[ProductKey]
    value: Optional[float]
    status: str
    present: bool
    complete: bool
    quality: str
    source_role: Optional[str] = None
    source_ref: Optional[str] = None
    generation: Any = None

    def __post_init__(self) -> None:
        _require_text(self.target_id, "target_id")
        _require_text(self.status, "factor point status")
        _require_text(self.quality, "factor point quality")
        if type(self.present) is not bool or type(self.complete) is not bool:
            raise TypeError("factor point present/complete flags must be booleans")
        if self.product_key is not None:
            object.__setattr__(
                self, "product_key", _normalize_product_key(self.product_key, "product_key")
            )
        if self.value is not None:
            if isinstance(self.value, bool) or not isinstance(self.value, Real):
                raise TypeError("factor point value must be a real number or None")
            object.__setattr__(self, "value", float(self.value))
        for name in ("source_role", "source_ref"):
            value = getattr(self, name)
            if value is not None:
                _require_text(value, name)


@dataclass(frozen=True)
class FactorSnapshotFacts:
    """Immutable calculation metadata copied from the shared factor snapshot."""

    readiness: str
    batch_complete: bool
    batch_id: str
    cohort_id: str
    calendar_id: str
    epoch_id: int
    close_time: datetime
    available_at: datetime
    factor_name: str
    mode: str
    direction: int
    source_sha256: str
    points: Tuple[FactorPoint, ...]

    def __post_init__(self) -> None:
        for name in (
            "readiness",
            "batch_id",
            "cohort_id",
            "calendar_id",
            "factor_name",
            "mode",
            "source_sha256",
        ):
            _require_text(getattr(self, name), name)
        if self.mode not in ("native", "build"):
            raise ValueError("factor mode must be 'native' or 'build'")
        if type(self.batch_complete) is not bool:
            raise TypeError("batch_complete must be a boolean")
        _require_epoch(self.epoch_id)
        if type(self.direction) is not int or self.direction not in (-1, 1):
            raise ValueError("factor direction must be exactly +1 or -1")
        object.__setattr__(self, "points", tuple(self.points))
        if any(not isinstance(point, FactorPoint) for point in self.points):
            raise TypeError("factor snapshot points must be FactorPoint values")
        _require_utc_datetime(self.close_time, "factor close_time")
        _require_utc_datetime(self.available_at, "factor available_at")


@dataclass(frozen=True)
class Alpha003PolicyInput:
    """Complete cohort plus factor evidence needed for target selection only."""

    cohort: CohortBatchFacts
    factor: FactorSnapshotFacts
    required_targets: Tuple[str, ...]
    authorized_targets: FrozenSet[str]
    eligible_grid_index: int = 0
    rebalance_every: int = DEFAULT_REBALANCE_GRIDS
    execution_mode: str = "LIVE"

    def __post_init__(self) -> None:
        if not isinstance(self.cohort, CohortBatchFacts):
            raise TypeError("cohort must be CohortBatchFacts")
        if not isinstance(self.factor, FactorSnapshotFacts):
            raise TypeError("factor must be FactorSnapshotFacts")
        required = tuple(self.required_targets)
        authorized = frozenset(self.authorized_targets)
        for target in required:
            _require_text(target, "required target")
        for target in authorized:
            _require_text(target, "authorized target")
        if len(set(required)) != len(required):
            raise ValueError("required_targets must be unique")
        if type(self.eligible_grid_index) is not int or self.eligible_grid_index < 0:
            raise ValueError("eligible_grid_index must be a non-negative integer")
        if type(self.rebalance_every) is not int or self.rebalance_every < 1:
            raise ValueError("rebalance_every must be a positive integer")
        if self.execution_mode not in ("LIVE", "REPLAY"):
            raise ValueError("execution_mode must be LIVE or REPLAY")
        object.__setattr__(self, "required_targets", required)
        object.__setattr__(self, "authorized_targets", authorized)


@dataclass(frozen=True)
class Alpha003SignalTarget:
    """Signed desired position; this is not an order or a position delta."""

    target_id: str
    product_key: ProductKey
    target_position: int
    raw_score: float
    oriented_score: float

    def __post_init__(self) -> None:
        _require_text(self.target_id, "target_id")
        object.__setattr__(
            self, "product_key", _normalize_product_key(self.product_key, "product_key")
        )
        if type(self.target_position) is not int or self.target_position not in (-1, 1):
            raise ValueError("signal target position must be +1 or -1")
        for name in ("raw_score", "oriented_score"):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, Real) or not math.isfinite(value):
                raise ValueError("signal target scores must be finite real numbers")
            object.__setattr__(self, name, float(value))


@dataclass(frozen=True)
class Alpha003TargetDecision:
    """Causal immutable result of the Alpha003 signal-target policy."""

    status: str
    reason: Optional[str]
    factor_name: str
    mode: str
    execution_mode: str
    direction: int
    source_sha256: str
    cohort_id: str
    batch_id: str
    close_time: datetime
    available_at: datetime
    eligible_grid_index: int
    rebalance_every: int
    authorized_targets: Tuple[str, ...]
    eligible_targets: Tuple[str, ...]
    targets: Tuple[Alpha003SignalTarget, ...]

    def __post_init__(self) -> None:
        if self.status not in ("TARGETS_READY", "BLOCKED"):
            raise ValueError("decision status must be TARGETS_READY or BLOCKED")
        if (self.status == "TARGETS_READY") != (self.reason is None):
            raise ValueError("ready decisions have no reason; blocked decisions require one")
        for name in (
            "factor_name",
            "mode",
            "execution_mode",
            "source_sha256",
            "cohort_id",
            "batch_id",
        ):
            _require_text(getattr(self, name), name)
        if type(self.direction) is not int or self.direction not in (-1, 1):
            raise ValueError("decision direction must be exactly +1 or -1")
        if self.execution_mode not in ("LIVE", "REPLAY"):
            raise ValueError("decision execution_mode must be LIVE or REPLAY")
        if type(self.eligible_grid_index) is not int or self.eligible_grid_index < 0:
            raise ValueError("decision eligible_grid_index must be non-negative")
        if type(self.rebalance_every) is not int or self.rebalance_every < 1:
            raise ValueError("decision rebalance_every must be positive")
        object.__setattr__(self, "authorized_targets", tuple(self.authorized_targets))
        object.__setattr__(self, "eligible_targets", tuple(self.eligible_targets))
        object.__setattr__(self, "targets", tuple(self.targets))
        _require_utc_datetime(self.close_time, "decision close_time")
        _require_utc_datetime(self.available_at, "decision available_at")


@dataclass(frozen=True)
class Alpha003RiskPolicy:
    """Frozen limits required before an opening order can be planned.

    The two-instrument/one-hand shape and five-grid rebalance cadence are fixed
    example mechanics. Every time, quote-age, funds, loss, and order-count
    budget must be supplied explicitly before this policy can plan a write.
    """

    risk_policy_id: str
    max_hold_eligible_bars: int
    preclose_grace_seconds: int
    run_end_policy: str
    quote_max_age_seconds: Decimal
    max_state_age_seconds: Decimal
    max_notional_per_position: Decimal
    max_total_notional: Decimal
    max_margin_per_position: Decimal
    max_total_margin: Decimal
    max_loss_per_position: Decimal
    max_total_loss: Decimal
    stop_loss_ticks: int
    max_order_intents_per_grid: int
    max_order_intents_per_run: int
    round_trip_fee_upper_bound_per_contract: Optional[Decimal] = None

    def __post_init__(self) -> None:
        _require_text(self.risk_policy_id, "risk_policy_id")
        if type(self.max_hold_eligible_bars) is not int or self.max_hold_eligible_bars < 1:
            raise ValueError("max_hold_eligible_bars must be a positive integer")
        if type(self.preclose_grace_seconds) is not int or self.preclose_grace_seconds < 0:
            raise ValueError("preclose_grace_seconds must be a non-negative integer")
        if self.run_end_policy not in ("CLOSE_ALL", "KEEP_POSITIONS"):
            raise ValueError("run_end_policy must be CLOSE_ALL or KEEP_POSITIONS")
        if type(self.max_order_intents_per_grid) is not int or self.max_order_intents_per_grid < 1:
            raise ValueError("max_order_intents_per_grid must be a positive integer")
        if type(self.max_order_intents_per_run) is not int or self.max_order_intents_per_run < 1:
            raise ValueError("max_order_intents_per_run must be a positive integer")
        if type(self.stop_loss_ticks) is not int or self.stop_loss_ticks < 1:
            raise ValueError("stop_loss_ticks must be a positive integer")
        for name in (
            "quote_max_age_seconds",
            "max_state_age_seconds",
            "max_notional_per_position",
            "max_total_notional",
            "max_margin_per_position",
            "max_total_margin",
            "max_loss_per_position",
            "max_total_loss",
        ):
            value = _positive_decimal(getattr(self, name), name)
            object.__setattr__(self, name, value)
        if self.round_trip_fee_upper_bound_per_contract is not None:
            object.__setattr__(
                self,
                "round_trip_fee_upper_bound_per_contract",
                _nonnegative_decimal(
                    self.round_trip_fee_upper_bound_per_contract,
                    "round_trip_fee_upper_bound_per_contract",
                ),
            )


@dataclass(frozen=True)
class Alpha003PositionFact:
    """One authoritative per-instrument position projection from the Broker."""

    target_id: Optional[str]
    instrument: str
    quantity: Optional[int]
    snapshot_id: str
    available_at: Optional[datetime]
    exchange: Optional[str] = None
    owner_strategy_scope: Optional[str] = None
    owner_intent_id: Optional[str] = None
    average_price: Optional[Decimal] = None
    stop_price: Optional[Decimal] = None
    held_eligible_bars: Optional[int] = None
    risk_average_price_lower: Optional[Decimal] = None
    risk_average_price_upper: Optional[Decimal] = None
    risk_stop_price_lower: Optional[Decimal] = None
    risk_stop_price_upper: Optional[Decimal] = None

    def __post_init__(self) -> None:
        if self.target_id is not None:
            _require_text(self.target_id, "position target_id")
        _require_text(self.instrument, "position instrument")
        _require_text(self.snapshot_id, "position snapshot_id")
        if self.exchange is not None:
            _require_text(self.exchange, "position exchange")
        if self.quantity is not None and type(self.quantity) is not int:
            raise TypeError("position quantity must be an integer number of hands or None")
        if self.available_at is not None:
            _require_utc_datetime(self.available_at, "position available_at")
        for name in ("owner_strategy_scope", "owner_intent_id"):
            value = getattr(self, name)
            if value is not None:
                _require_text(value, name)
        price_sources = {
            "average_price": self.average_price,
            "stop_price": self.stop_price,
        }
        for name in ("average_price", "stop_price"):
            value = getattr(self, name)
            if value is not None:
                value = _positive_decimal(value, name)
                object.__setattr__(self, name, value)
        for source_name, lower_name, upper_name in (
            ("average_price", "risk_average_price_lower", "risk_average_price_upper"),
            ("stop_price", "risk_stop_price_lower", "risk_stop_price_upper"),
        ):
            source = price_sources[source_name]
            lower = getattr(self, lower_name)
            upper = getattr(self, upper_name)
            if source is None:
                lower = upper = None
            else:
                canonical_source = _positive_decimal(source, source_name)
                if lower is None:
                    lower = _risk_native_float_envelope(source, upward=False)
                if upper is None:
                    upper = _risk_native_float_envelope(source, upward=True)
            if lower is not None:
                lower = _nonnegative_decimal(lower, lower_name)
                if lower > canonical_source:
                    raise ValueError("{} exceeds its source price".format(lower_name))
                object.__setattr__(self, lower_name, lower)
            if upper is not None:
                upper = _positive_decimal(upper, upper_name)
                if upper < canonical_source:
                    raise ValueError("{} is below its source price".format(upper_name))
                object.__setattr__(self, upper_name, upper)
            if lower is None:
                object.__setattr__(self, lower_name, None)
            if upper is None:
                object.__setattr__(self, upper_name, None)
        if self.held_eligible_bars is not None and (
            type(self.held_eligible_bars) is not int or self.held_eligible_bars < 0
        ):
            raise ValueError("held_eligible_bars must be a non-negative integer or None")


@dataclass(frozen=True)
class Alpha003WorkingOrderFact:
    """A bounded projection of a real order or unresolved intent."""

    target_id: Optional[str]
    instrument: str
    order_ref: str
    state: str
    side: Optional[str]
    position_effect: Optional[str]
    remaining_quantity: Optional[int]
    owner_strategy_scope: Optional[str]
    owner_intent_id: Optional[str]
    exchange: Optional[str] = None
    broker_order_ref: Optional[int] = None

    def __post_init__(self) -> None:
        for name in ("instrument", "order_ref", "state"):
            _require_text(getattr(self, name), name)
        if self.exchange is not None:
            _require_text(self.exchange, "working order exchange")
        if self.broker_order_ref is not None and (
            type(self.broker_order_ref) is not int or self.broker_order_ref < 1
        ):
            raise ValueError("broker_order_ref must be a positive integer or None")
        if self.target_id is not None:
            _require_text(self.target_id, "working order target_id")
        if self.side is not None and self.side not in ("BUY", "SELL"):
            raise ValueError("working order side is invalid")
        if self.position_effect is not None and self.position_effect not in ("OPEN", "CLOSE"):
            raise ValueError("working order position_effect is invalid")
        if self.remaining_quantity is not None and (
            type(self.remaining_quantity) is not int or self.remaining_quantity < 0
        ):
            raise ValueError("remaining_quantity must be a non-negative integer or None")
        for name in ("owner_strategy_scope", "owner_intent_id"):
            value = getattr(self, name)
            if value is not None:
                _require_text(value, name)


@dataclass(frozen=True)
class Alpha003QuoteFact:
    """A current executable quote; it is separate from the completed factor bar."""

    instrument: str
    source_ref: Optional[str]
    metadata_snapshot_id: Optional[str]
    generation: Optional[int]
    sequence: Optional[int]
    event_time: Optional[datetime]
    available_at: Optional[datetime]
    bid: Optional[Decimal]
    ask: Optional[Decimal]
    bid_size: Optional[Decimal]
    ask_size: Optional[Decimal]
    tick_size: Optional[Decimal]
    lower_limit: Optional[Decimal]
    upper_limit: Optional[Decimal]
    quality: str = "GOOD"
    exchange: Optional[str] = None
    evidence_source: str = "REGISTERED_SIM"
    risk_bid_lower: Optional[Decimal] = None
    risk_bid_upper: Optional[Decimal] = None
    risk_ask_lower: Optional[Decimal] = None
    risk_ask_upper: Optional[Decimal] = None
    risk_bid_size_lower: Optional[Decimal] = None
    risk_ask_size_lower: Optional[Decimal] = None
    risk_tick_size_upper: Optional[Decimal] = None

    def __post_init__(self) -> None:
        for name in ("instrument", "quality"):
            _require_text(getattr(self, name), name)
        if self.exchange is not None:
            _require_text(self.exchange, "quote exchange")
        if self.evidence_source not in ("REGISTERED_SIM", "REPLAY_TAPE"):
            raise ValueError("unsupported quote evidence source")
        for name in ("source_ref", "metadata_snapshot_id"):
            value = getattr(self, name)
            if value is not None:
                _require_text(value, name)
        if self.generation is not None and (
            type(self.generation) is not int or self.generation < 1
        ):
            raise ValueError("quote generation must be a positive integer or None")
        if self.sequence is not None and (type(self.sequence) is not int or self.sequence < 0):
            raise ValueError("quote sequence must be a non-negative integer or None")
        if self.event_time is not None:
            _require_utc_datetime(self.event_time, "quote event_time")
        if self.available_at is not None:
            _require_utc_datetime(self.available_at, "quote available_at")
        for source_name, lower_name, upper_name in (
            ("bid", "risk_bid_lower", "risk_bid_upper"),
            ("ask", "risk_ask_lower", "risk_ask_upper"),
        ):
            source = getattr(self, source_name)
            lower = getattr(self, lower_name)
            upper = getattr(self, upper_name)
            if source is None:
                lower = upper = None
            else:
                canonical_source = _positive_decimal(source, source_name)
                if lower is None:
                    lower = _risk_native_float_envelope(source, upward=False)
                if upper is None:
                    upper = _risk_native_float_envelope(source, upward=True)
            if lower is not None:
                lower = _nonnegative_decimal(lower, lower_name)
                if lower > canonical_source:
                    raise ValueError("{} exceeds its source price".format(lower_name))
                object.__setattr__(self, lower_name, lower)
            if upper is not None:
                upper = _positive_decimal(upper, upper_name)
                if upper < canonical_source:
                    raise ValueError("{} is below its source price".format(upper_name))
                object.__setattr__(self, upper_name, upper)
            if lower is None:
                object.__setattr__(self, lower_name, None)
            if upper is None:
                object.__setattr__(self, upper_name, None)
        for source_name, target_name in (
            ("bid_size", "risk_bid_size_lower"),
            ("ask_size", "risk_ask_size_lower"),
        ):
            source = getattr(self, source_name)
            bound = getattr(self, target_name)
            if source is None:
                bound = None
            else:
                canonical_source = _positive_decimal(source, source_name)
                if bound is None:
                    bound = _risk_native_float_envelope(source, upward=False)
            if bound is not None:
                if _nonnegative_decimal(bound, target_name) > canonical_source:
                    raise ValueError("{} exceeds its source size".format(target_name))
                object.__setattr__(self, target_name, _nonnegative_decimal(bound, target_name))
            else:
                object.__setattr__(self, target_name, None)
        risk_tick = self.risk_tick_size_upper
        if self.tick_size is None:
            risk_tick = None
        else:
            canonical_tick = _positive_decimal(self.tick_size, "tick_size")
            if risk_tick is None:
                risk_tick = _risk_native_float_envelope(self.tick_size, upward=True)
        if risk_tick is not None:
            if _positive_decimal(risk_tick, "risk_tick_size_upper") < canonical_tick:
                raise ValueError("risk tick upper bound is below its source tick")
            object.__setattr__(
                self,
                "risk_tick_size_upper",
                _positive_decimal(risk_tick, "risk_tick_size_upper"),
            )
        else:
            object.__setattr__(self, "risk_tick_size_upper", None)
        for name in (
            "bid",
            "ask",
            "bid_size",
            "ask_size",
            "tick_size",
            "lower_limit",
            "upper_limit",
        ):
            raw = getattr(self, name)
            if raw is not None:
                if name in ("lower_limit", "upper_limit"):
                    value = _decimal_number(raw, name)
                else:
                    value = _positive_decimal(raw, name)
                object.__setattr__(self, name, value)


@dataclass(frozen=True)
class Alpha003InstrumentRiskFact:
    """Contract metadata and permission for one actual listed instrument."""

    target_id: str
    instrument: str
    snapshot_id: Optional[str]
    available_at: Optional[datetime]
    trading_permitted: Optional[bool]
    multiplier: Optional[Decimal]
    long_margin_per_hand: Optional[Decimal]
    short_margin_per_hand: Optional[Decimal]
    exchange: Optional[str] = None
    tick_size: Optional[Decimal] = None
    lower_limit: Optional[Decimal] = None
    upper_limit: Optional[Decimal] = None
    route_permitted: Optional[bool] = None
    round_trip_fee_upper_bound_per_contract: Optional[Decimal] = None
    commission_fee_required: bool = False
    commission_fee_status: str = "NOT_REQUIRED"
    risk_multiplier_upper: Optional[Decimal] = None
    risk_long_margin_per_hand_upper: Optional[Decimal] = None
    risk_short_margin_per_hand_upper: Optional[Decimal] = None
    risk_tick_size_upper: Optional[Decimal] = None

    def __post_init__(self) -> None:
        for name in ("target_id", "instrument"):
            _require_text(getattr(self, name), name)
        if self.snapshot_id is not None:
            _require_text(self.snapshot_id, "instrument snapshot_id")
        if self.available_at is not None:
            _require_utc_datetime(self.available_at, "instrument risk available_at")
        if self.exchange is not None:
            _require_text(self.exchange, "instrument risk exchange")
        if self.trading_permitted is not None and type(self.trading_permitted) is not bool:
            raise TypeError("trading_permitted must be bool or None")
        if self.route_permitted is not None and type(self.route_permitted) is not bool:
            raise TypeError("route_permitted must be bool or None")
        if type(self.commission_fee_required) is not bool:
            raise TypeError("commission_fee_required must be bool")
        if self.commission_fee_status not in {
            "NOT_REQUIRED",
            "IDENTITY_UNAVAILABLE",
            "QUERY_UNAVAILABLE",
            "EVIDENCE_INVALID",
            "RATE_UNAVAILABLE",
            "RATE_INVALID",
            "AVAILABLE",
        }:
            raise ValueError("commission_fee_status is unsupported")
        for source_name, bound_name in (
            ("multiplier", "risk_multiplier_upper"),
            ("long_margin_per_hand", "risk_long_margin_per_hand_upper"),
            ("short_margin_per_hand", "risk_short_margin_per_hand_upper"),
            ("tick_size", "risk_tick_size_upper"),
        ):
            source = getattr(self, source_name)
            bound = getattr(self, bound_name)
            if source is None:
                bound = None
            else:
                canonical_source = _positive_decimal(source, source_name)
                if bound is None:
                    bound = _risk_native_float_envelope(source, upward=True)
            if bound is not None:
                bound = _positive_decimal(bound, bound_name)
                if bound < canonical_source:
                    raise ValueError("{} is below its source value".format(bound_name))
                object.__setattr__(self, bound_name, bound)
            else:
                object.__setattr__(self, bound_name, None)
        for name in (
            "multiplier",
            "long_margin_per_hand",
            "short_margin_per_hand",
            "tick_size",
            "lower_limit",
            "upper_limit",
            "round_trip_fee_upper_bound_per_contract",
        ):
            value = getattr(self, name)
            if value is not None:
                if name == "round_trip_fee_upper_bound_per_contract":
                    value = _nonnegative_decimal(value, name)
                elif name in ("lower_limit", "upper_limit"):
                    value = _decimal_number(value, name)
                else:
                    value = _positive_decimal(value, name)
                object.__setattr__(self, name, value)
        if (
            self.lower_limit is not None
            and self.upper_limit is not None
            and self.lower_limit > self.upper_limit
        ):
            raise ValueError("instrument price limits are inverted")


@dataclass(frozen=True)
class Alpha003AccountRiskFact:
    """Fresh account/route facts needed to consider any new exposure."""

    account_scope: str
    snapshot_id: str
    available_at: datetime
    route_permitted: Optional[bool]
    available_margin: Optional[Decimal]
    used_margin: Optional[Decimal]
    current_notional: Optional[Decimal]
    current_worst_case_loss: Optional[Decimal]
    cash: Optional[Decimal] = None
    equity: Optional[Decimal] = None

    def __post_init__(self) -> None:
        _require_text(self.account_scope, "account_scope")
        _require_text(self.snapshot_id, "account snapshot_id")
        _require_utc_datetime(self.available_at, "account available_at")
        if self.route_permitted is not None and type(self.route_permitted) is not bool:
            raise TypeError("route_permitted must be bool or None")
        for name in (
            "available_margin",
            "used_margin",
            "current_notional",
            "current_worst_case_loss",
            "cash",
            "equity",
        ):
            value = getattr(self, name)
            if value is not None:
                value = _risk_native_float_envelope(
                    value, upward=name != "available_margin"
                )
                if value is None:
                    raise ValueError("{} must be a finite non-negative risk value".format(name))
                value = _nonnegative_decimal(value, name)
                object.__setattr__(self, name, value)


@dataclass(frozen=True)
class Alpha003OrderPlanningInput:
    """Actual Broker evidence plus an optional fresh target decision."""

    strategy_scope: str
    evaluated_at: datetime
    risk_evidence_available_at: Optional[datetime]
    session_close_at: Optional[datetime]
    run_end: bool
    risk_policy: Optional[Alpha003RiskPolicy]
    account: Optional[Alpha003AccountRiskFact]
    positions: Tuple[Alpha003PositionFact, ...]
    working_orders: Tuple[Alpha003WorkingOrderFact, ...]
    quotes: Tuple[Alpha003QuoteFact, ...]
    instruments: Tuple[Alpha003InstrumentRiskFact, ...]
    target_decision: Optional[Alpha003TargetDecision] = None
    run_order_intents_used: Optional[int] = None
    execution_blockers: Tuple[str, ...] = ()
    eligible_grid_ordinal: Optional[int] = None
    risk_reduction_ready: bool = True
    risk_reduction_blockers: Tuple[str, ...] = ()
    open_risk_ready: bool = True
    open_risk_blockers: Tuple[str, ...] = ()
    order_cancel_ready: bool = False
    order_cancel_blockers: Tuple[str, ...] = ()
    evidence_source: str = "REGISTERED_SIM"
    dated_close_legs: Tuple[Any, ...] = ()
    dated_query_set_id: Optional[str] = None
    dated_snapshot_id: Optional[str] = None
    dated_account_fingerprint: Optional[str] = None
    dated_connection_generation: Optional[int] = None
    dated_trading_day: Optional[str] = None
    dated_available_at: Optional[datetime] = None
    execution_target_ids: Optional[Tuple[str, ...]] = None

    def __post_init__(self) -> None:
        _require_text(self.strategy_scope, "strategy_scope")
        _require_utc_datetime(self.evaluated_at, "evaluated_at")
        if self.risk_evidence_available_at is not None:
            _require_utc_datetime(self.risk_evidence_available_at, "risk_evidence_available_at")
        if self.session_close_at is not None:
            _require_utc_datetime(self.session_close_at, "session_close_at")
        if type(self.run_end) is not bool:
            raise TypeError("run_end must be a boolean")
        for name in ("risk_reduction_ready", "open_risk_ready", "order_cancel_ready"):
            if type(getattr(self, name)) is not bool:
                raise TypeError("{} must be a boolean".format(name))
        if self.evidence_source not in ("REGISTERED_SIM", "CAUSAL_REPLAY"):
            raise ValueError("evidence_source must be REGISTERED_SIM or CAUSAL_REPLAY")
        for name, item_type in (
            ("positions", Alpha003PositionFact),
            ("working_orders", Alpha003WorkingOrderFact),
            ("quotes", Alpha003QuoteFact),
            ("instruments", Alpha003InstrumentRiskFact),
        ):
            items = tuple(getattr(self, name))
            if any(not isinstance(item, item_type) for item in items):
                raise TypeError("{} contains an unsupported fact type".format(name))
            object.__setattr__(self, name, items)
        object.__setattr__(self, "dated_close_legs", tuple(self.dated_close_legs))
        if self.execution_target_ids is not None:
            target_ids = self.execution_target_ids
            if (
                type(target_ids) is not tuple
                or not target_ids
                or any(
                    type(target_id) is not str or not target_id or target_id != target_id.strip()
                    for target_id in target_ids
                )
                or len(set(target_ids)) != len(target_ids)
            ):
                raise ValueError(
                    "execution_target_ids must be a non-empty immutable unique target tuple"
                )
        for name in (
            "dated_query_set_id",
            "dated_snapshot_id",
            "dated_account_fingerprint",
            "dated_trading_day",
        ):
            value = getattr(self, name)
            if value is not None and (type(value) is not str or not value):
                raise ValueError("{} must be non-empty text or None".format(name))
        if self.dated_connection_generation is not None and (
            type(self.dated_connection_generation) is not int
            or self.dated_connection_generation < 0
        ):
            raise ValueError("dated_connection_generation must be a non-negative int or None")
        if self.dated_available_at is not None:
            _require_utc_datetime(self.dated_available_at, "dated_available_at")
        if self.risk_policy is not None and not isinstance(self.risk_policy, Alpha003RiskPolicy):
            raise TypeError("risk_policy must be Alpha003RiskPolicy or None")
        if self.account is not None and not isinstance(self.account, Alpha003AccountRiskFact):
            raise TypeError("account must be Alpha003AccountRiskFact or None")
        if self.target_decision is not None and not isinstance(
            self.target_decision, Alpha003TargetDecision
        ):
            raise TypeError("target_decision must be Alpha003TargetDecision or None")
        if self.run_order_intents_used is not None and (
            type(self.run_order_intents_used) is not int or self.run_order_intents_used < 0
        ):
            raise ValueError("run_order_intents_used must be a non-negative integer or None")
        for name in (
            "execution_blockers",
            "risk_reduction_blockers",
            "open_risk_blockers",
            "order_cancel_blockers",
        ):
            blockers = tuple(getattr(self, name))
            if any(type(item) is not str or not item for item in blockers):
                raise ValueError("{} must contain non-empty strings".format(name))
            object.__setattr__(self, name, blockers)
        if self.eligible_grid_ordinal is not None and (
            type(self.eligible_grid_ordinal) is not int or self.eligible_grid_ordinal < 1
        ):
            raise ValueError("eligible_grid_ordinal must be positive or None")


@dataclass(frozen=True)
class Alpha003OrderAction:
    """One validated Broker-level action, never a provider/SDK command."""

    action: str
    target_id: str
    instrument: str
    side: str
    position_effect: str
    quantity: int
    limit_price: Optional[Decimal]
    offset: str
    reason: str
    order_ref: Optional[str] = None
    owner_intent_id: Optional[str] = None
    planned_stop_price: Optional[Decimal] = None
    exchange: Optional[str] = None
    decision_available_at: Optional[datetime] = None
    entry_grid_ordinal: Optional[int] = None
    broker_order_ref: Optional[int] = None
    position_side: Optional[str] = None
    dated_position_side: Optional[str] = None
    position_date: Optional[str] = None
    offset_flag: Optional[str] = None
    hedge_flag: Optional[str] = None
    dated_query_set_id: Optional[str] = None
    dated_snapshot_id: Optional[str] = None
    dated_account_fingerprint: Optional[str] = None
    dated_connection_generation: Optional[int] = None
    dated_trading_day: Optional[str] = None
    dated_available_at: Optional[datetime] = None
    dated_source_row_ids: Tuple[str, ...] = ()
    dated_opening_execution_ids: Tuple[str, ...] = ()
    dated_close_execution_ids: Tuple[str, ...] = ()


@dataclass(frozen=True)
class Alpha003ReplayQuoteFact:
    """One explicit immutable quote-tape row for local causal replay."""

    instrument: str
    exchange: str
    event_time: datetime
    available_at: datetime
    bid: Decimal
    ask: Decimal
    source_ref: str
    quote_id: str

    def __post_init__(self) -> None:
        for name in ("instrument", "exchange", "source_ref", "quote_id"):
            _require_text(getattr(self, name), "replay quote " + name)
        _require_utc_datetime(self.event_time, "replay quote event_time")
        _require_utc_datetime(self.available_at, "replay quote available_at")
        object.__setattr__(self, "bid", _positive_decimal(self.bid, "replay bid"))
        object.__setattr__(self, "ask", _positive_decimal(self.ask, "replay ask"))
        if self.bid > self.ask:
            raise ValueError("replay quote bid must not exceed ask")
        if self.available_at < self.event_time:
            raise ValueError("replay quote cannot be available before its event")


@dataclass(frozen=True)
class Alpha003OpenRiskLegCandidate:
    """One planner-computed OPEN risk upper bound, not a durable reservation."""

    target_id: str
    instrument: str
    exchange: str
    side: str
    quantity: int
    entry_price: Decimal
    stop_price: Decimal
    multiplier: Decimal
    margin: Decimal
    notional: Decimal
    stop_loss: Decimal
    round_trip_fee_upper_bound: Decimal
    worst_case_loss: Decimal
    commission_fee_required: bool
    commission_fee_status: str
    instrument_snapshot_id: str
    quote_source_ref: Optional[str]
    quote_metadata_snapshot_id: str
    quote_generation: Optional[int]
    quote_sequence: Optional[int]
    quote_event_time: datetime
    quote_available_at: datetime
    quote_bid: Decimal
    quote_ask: Decimal
    quote_bid_size: Optional[Decimal]
    quote_ask_size: Optional[Decimal]

    def __post_init__(self) -> None:
        for name in (
            "target_id",
            "instrument",
            "exchange",
            "instrument_snapshot_id",
            "quote_metadata_snapshot_id",
        ):
            _require_text(getattr(self, name), "open risk leg " + name)
        if self.quote_source_ref is not None:
            _require_text(self.quote_source_ref, "open risk quote_source_ref")
        if self.side not in ("BUY", "SELL"):
            raise ValueError("open risk leg side is invalid")
        if type(self.commission_fee_required) is not bool:
            raise TypeError("open risk commission_fee_required must be bool")
        if self.commission_fee_status not in {
            "NOT_REQUIRED",
            "IDENTITY_UNAVAILABLE",
            "QUERY_UNAVAILABLE",
            "EVIDENCE_INVALID",
            "RATE_UNAVAILABLE",
            "RATE_INVALID",
            "AVAILABLE",
        }:
            raise ValueError("open risk commission_fee_status is unsupported")
        if type(self.quantity) is not int or self.quantity < 1:
            raise ValueError("open risk leg quantity must be positive")
        for name in ("quote_generation", "quote_sequence"):
            value = getattr(self, name)
            if value is not None and (type(value) is not int or value < 0):
                raise ValueError("open risk quote identity must be non-negative or None")
        for name in ("quote_event_time", "quote_available_at"):
            _require_utc_datetime(getattr(self, name), "open risk " + name)
        for name in (
            "entry_price",
            "stop_price",
            "multiplier",
            "margin",
            "notional",
            "quote_bid",
            "quote_ask",
        ):
            value = _positive_decimal(getattr(self, name), "open risk " + name)
            object.__setattr__(self, name, value)
        for name in ("stop_loss", "round_trip_fee_upper_bound", "worst_case_loss"):
            value = _nonnegative_decimal(getattr(self, name), "open risk " + name)
            object.__setattr__(self, name, value)
        for name in ("quote_bid_size", "quote_ask_size"):
            value = getattr(self, name)
            if value is not None:
                object.__setattr__(self, name, _positive_decimal(value, "open risk " + name))
        if self.quote_event_time > self.quote_available_at or self.quote_bid > self.quote_ask:
            raise ValueError("open risk quote identity is invalid")
        if self.worst_case_loss < self.stop_loss or self.worst_case_loss < self.round_trip_fee_upper_bound:
            raise ValueError("open risk loss bound is below a component")


@dataclass(frozen=True)
class Alpha003OpenRiskCandidate:
    """Planner output for a possible OPEN set; not an active risk reservation.

    The Journal must separately persist and enforce a reservation before either
    pair leg can dispatch. These values preserve the exact planner projection
    so a later trusted Store/Journal path can verify it without recomputing from
    rounded Broker fields.
    """

    schema: str
    evidence_source: str
    strategy_scope: str
    batch_id: str
    risk_policy_id: str
    account_scope: str
    account_snapshot_id: str
    query_set_id: Optional[str]
    account_fingerprint: Optional[str]
    connection_generation: Optional[int]
    trading_day: Optional[str]
    source_snapshot_id: Optional[str]
    eligible_grid_ordinal: Optional[int]
    account_available_at: datetime
    risk_evidence_available_at: datetime
    available_margin: Decimal
    used_margin: Decimal
    current_notional: Decimal
    current_worst_case_loss: Decimal
    held_fee_reserve: Decimal
    required_margin: Decimal
    added_notional: Decimal
    added_loss: Decimal
    projected_total_margin: Decimal
    projected_total_notional: Decimal
    projected_total_worst_case_loss: Decimal
    max_total_margin: Decimal
    max_total_notional: Decimal
    max_total_loss: Decimal
    legs: Tuple[Alpha003OpenRiskLegCandidate, ...]

    def __post_init__(self) -> None:
        for name in (
            "schema",
            "evidence_source",
            "strategy_scope",
            "batch_id",
            "risk_policy_id",
            "account_scope",
            "account_snapshot_id",
        ):
            _require_text(getattr(self, name), "open risk candidate " + name)
        for name in (
            "query_set_id",
            "account_fingerprint",
            "trading_day",
            "source_snapshot_id",
        ):
            value = getattr(self, name)
            if value is not None:
                _require_text(value, "open risk candidate " + name)
        if self.connection_generation is not None and (
            type(self.connection_generation) is not int or self.connection_generation < 1
        ):
            raise ValueError("open risk candidate connection generation is invalid")
        if self.eligible_grid_ordinal is not None and (
            type(self.eligible_grid_ordinal) is not int or self.eligible_grid_ordinal < 1
        ):
            raise ValueError("open risk candidate grid ordinal is invalid")
        if self.schema != "backtrader.alpha003.open_risk_candidate.v1":
            raise ValueError("open risk candidate schema is invalid")
        if self.evidence_source not in ("REGISTERED_SIM", "CAUSAL_REPLAY"):
            raise ValueError("open risk candidate evidence source is invalid")
        for name in ("account_available_at", "risk_evidence_available_at"):
            _require_utc_datetime(getattr(self, name), "open risk candidate " + name)
        for name in (
            "available_margin",
            "used_margin",
            "current_notional",
            "current_worst_case_loss",
            "held_fee_reserve",
            "required_margin",
            "added_notional",
            "added_loss",
            "projected_total_margin",
            "projected_total_notional",
            "projected_total_worst_case_loss",
            "max_total_margin",
            "max_total_notional",
            "max_total_loss",
        ):
            value = _nonnegative_decimal(getattr(self, name), "open risk candidate " + name)
            object.__setattr__(self, name, value)
        legs = tuple(self.legs)
        if not legs or any(not isinstance(item, Alpha003OpenRiskLegCandidate) for item in legs):
            raise ValueError("open risk candidate requires typed legs")
        if len({item.target_id for item in legs}) != len(legs):
            raise ValueError("open risk candidate targets must be unique")
        object.__setattr__(self, "legs", legs)


@dataclass(frozen=True)
class Alpha003OrderPlan:
    """Pure actual-position/quote/risk projection for ordinary Strategy methods."""

    status: str
    reason: Optional[str]
    actions: Tuple[Alpha003OrderAction, ...]
    decision_batch_id: Optional[str]
    decision_available_at: Optional[datetime]
    account_snapshot_id: Optional[str]
    open_risk_candidate: Optional[Alpha003OpenRiskCandidate] = None


# The example admits at most one contract per target. Preserve one first
# disposition request for each possible exposure, plus a cancellation for each
# active or newly proposed OPEN. Retries use only capacity beyond the remaining
# obligations and the durable run-wide cap; this planner does not claim a
# per-owner retry ledger or guaranteed provider fills.
_FIRST_CLOSE_INTENT_RESERVE_PER_TARGET = 1


def _future_exit_intent_reserve(
    inputs: Alpha003OrderPlanningInput,
    *,
    planned_actions: Tuple[Alpha003OrderAction, ...] = (),
    proposed_open_actions: Tuple[Alpha003OrderAction, ...] = (),
) -> int:
    """Return uncovered first-exit capacity after the planned actions.

    A target with a CLOSE in this plan (or an already active CLOSE) has its
    first close intent charged or in flight. A planned CANCEL covers the
    current cancellation request, while possible exposure from that OPEN
    still reserves one CLOSE. Targets with a current position, an active OPEN,
    or a proposed OPEN are counted once even when a partial fill and remainder
    coexist. This is a planning reserve, not a second durable ledger.
    """

    planned_cancel_targets = {
        action.target_id
        for action in planned_actions
        if action.action == "CANCEL" and action.position_effect == "OPEN"
    }
    planned_close_targets = {
        action.target_id
        for action in planned_actions
        if action.action == "SUBMIT" and action.position_effect == "CLOSE"
    }
    proposed_targets = {action.target_id for action in proposed_open_actions}
    open_orders = tuple(
        order
        for order in inputs.working_orders
        if order.position_effect == "OPEN"
        and order.state in {"ACCEPTED", "PARTIAL", "CANCEL_PENDING"}
    )
    cancellable_open_orders = tuple(
        order for order in open_orders if order.state in {"ACCEPTED", "PARTIAL"}
    )
    active_close_targets = {
        order.target_id
        for order in inputs.working_orders
        if order.position_effect == "CLOSE"
        and order.state in {"ACCEPTED", "PARTIAL", "CANCEL_PENDING"}
    }
    exposed_targets = {
        position.target_id for position in inputs.positions if position.quantity not in (None, 0)
    }
    exposed_targets.update(order.target_id for order in open_orders)
    exposed_targets.update(proposed_targets)

    covered_close_targets = planned_close_targets | active_close_targets
    close_reserve = (
        len(exposed_targets - covered_close_targets) * _FIRST_CLOSE_INTENT_RESERVE_PER_TARGET
    )
    cancel_reserve = sum(
        1 for order in cancellable_open_orders if order.target_id not in planned_cancel_targets
    )
    active_open_targets = {order.target_id for order in open_orders}
    cancel_reserve += len(proposed_targets - active_open_targets)
    return close_reserve + cancel_reserve


def _dated_close_actions_for_position(
    inputs: Alpha003OrderPlanningInput,
    position: Alpha003PositionFact,
    *,
    side: str,
    limit_price: Decimal,
    reason: str,
) -> Tuple[Tuple[Alpha003OrderAction, ...], Optional[str]]:
    """Map exact bridge-proved SHFE/INE date buckets to Broker close intents."""

    if inputs.evidence_source == "CAUSAL_REPLAY":
        return (), "REPLAY_DATED_CLOSE_FACTS_UNAVAILABLE"
    if position.exchange not in {"SHFE", "INE"}:
        return (), "DATED_CLOSE_NOT_REQUIRED"

    from backtrader.stores.factor_execution_facts import (
        FactorExecutionDatedCloseLegFacts,
        FactorExecutionDatedInventoryRow,
    )

    legs = tuple(
        leg
        for leg in inputs.dated_close_legs
        if getattr(leg, "target_id", None) == position.target_id
    )
    if not legs:
        return (), "DATED_CLOSE_FACTS_UNAVAILABLE"
    if any(type(leg) is not FactorExecutionDatedCloseLegFacts for leg in legs):
        return (), "DATED_CLOSE_FACT_TYPE_INVALID"
    if any(leg.ready is not True or leg.blockers for leg in legs):
        return (), "DATED_CLOSE_PROOF_BLOCKED"

    expected_position_side = "LONG" if position.quantity > 0 else "SHORT"
    expected_date_codes = {
        "TODAY": ("1", "3", "close_today"),
        "HISTORY": ("2", "4", "close_yesterday"),
    }
    seen_buckets = set()
    row_ids = set()
    actions = []
    total_quantity = 0
    for leg in sorted(
        legs,
        key=lambda item: (
            0 if item.position_date == "TODAY" else 1,
            item.hedge_flag or "",
            item.position_side or "",
        ),
    ):
        if (
            leg.target_id != position.target_id
            or leg.instrument != position.instrument
            or leg.exchange != position.exchange
            or leg.position_side != expected_position_side
            or leg.side != side
            or leg.owner_strategy_scope != inputs.strategy_scope
            or leg.owner_intent_id != position.owner_intent_id
        ):
            return (), "DATED_CLOSE_OWNER_OR_ROUTE_MISMATCH"
        if (
            inputs.dated_query_set_id is None
            or inputs.dated_snapshot_id is None
            or inputs.dated_account_fingerprint is None
            or inputs.dated_connection_generation is None
            or inputs.dated_trading_day is None
            or inputs.dated_available_at is None
            or leg.query_set_id != inputs.dated_query_set_id
            or leg.snapshot_id != inputs.dated_snapshot_id
            or leg.account_fingerprint != inputs.dated_account_fingerprint
            or leg.connection_generation != inputs.dated_connection_generation
            or leg.trading_day != inputs.dated_trading_day
            or leg.available_at != inputs.dated_available_at
            or leg.available_at > inputs.evaluated_at
        ):
            return (), "DATED_CLOSE_PROVENANCE_MISMATCH"
        expected_codes = expected_date_codes.get(leg.position_date)
        if (
            expected_codes is None
            or leg.offset != expected_codes[2]
            or leg.offset_flag != expected_codes[1]
        ):
            return (), "DATED_CLOSE_OFFSET_OR_HEDGE_INVALID"
        # The current registered SimNow encoder routes only speculation
        # HedgeFlag=1. Other provider hedge modes remain blocked until the
        # shared Store can preserve them end to end.
        if leg.hedge_flag != "1":
            return (), "DATED_CLOSE_HEDGE_UNSUPPORTED"
        bucket_identity = (leg.position_side, leg.hedge_flag, leg.position_date)
        if bucket_identity in seen_buckets:
            return (), "DATED_CLOSE_BUCKET_DUPLICATE"
        seen_buckets.add(bucket_identity)

        source_ids = tuple(leg.source_row_ids)
        if (
            not source_ids
            or len(set(source_ids)) != len(source_ids)
            or any(type(row_id) is not str or not row_id for row_id in source_ids)
            or row_ids.intersection(source_ids)
        ):
            return (), "DATED_CLOSE_SOURCE_ROWS_INVALID"
        row_ids.update(source_ids)
        rows = tuple(leg.inventory_rows)
        if (
            not rows
            or len(rows) != len(source_ids)
            or any(type(row) is not FactorExecutionDatedInventoryRow for row in rows)
            or {row.source_row_id for row in rows} != set(source_ids)
        ):
            return (), "DATED_CLOSE_SOURCE_ROWS_INCOMPLETE"
        expected_position_code = expected_codes[0]
        freeze_values = (
            "long_frozen",
            "short_frozen",
            "comb_long_frozen",
            "comb_short_frozen",
            "strike_frozen",
            "abandon_frozen",
            "long_frozen_amount",
            "short_frozen_amount",
            "frozen_margin",
            "frozen_cash",
            "frozen_commission",
            "strike_frozen_amount",
            "yd_strike_frozen",
        )
        observed_field_aliases = (
            ("InstrumentID", "instrument_id"),
            ("ExchangeID", "exchange_id"),
            ("PosiDirection", "position_direction"),
            ("HedgeFlag", "hedge_flag"),
            ("PositionDate", "position_date"),
            ("TradingDay", "trading_day"),
            ("Position", "position"),
            ("TodayPosition", "today_position"),
            ("YdPosition", "yd_position"),
            ("LongFrozen", "long_frozen"),
            ("ShortFrozen", "short_frozen"),
            ("CombLongFrozen", "comb_long_frozen"),
            ("CombShortFrozen", "comb_short_frozen"),
            ("StrikeFrozen", "strike_frozen"),
            ("AbandonFrozen", "abandon_frozen"),
            ("LongFrozenAmount", "long_frozen_amount"),
            ("ShortFrozenAmount", "short_frozen_amount"),
            ("FrozenMargin", "frozen_margin"),
            ("FrozenCash", "frozen_cash"),
            ("FrozenCommission", "frozen_commission"),
            ("StrikeFrozenAmount", "strike_frozen_amount"),
            ("YdStrikeFrozen", "yd_strike_frozen"),
        )
        for row in rows:
            observed_fields = set(row.observed_fields)
            if (
                row.blockers
                or any(
                    not observed_fields.intersection(aliases) for aliases in observed_field_aliases
                )
                or row.instrument != position.instrument
                or row.exchange != position.exchange
                or row.position_side != leg.position_side
                or row.hedge_flag != leg.hedge_flag
                or row.hedge_flag != "1"
                or row.position_date != leg.position_date
                or row.position_date_code != expected_position_code
                or row.trading_day != inputs.dated_trading_day
                or row.query_set_id != inputs.dated_query_set_id
                or row.snapshot_id != inputs.dated_snapshot_id
                or row.connection_generation != inputs.dated_connection_generation
                or row.account_fingerprint != inputs.dated_account_fingerprint
                or row.position is None
                or row.position <= 0
                or row.today_position is None
                or row.yd_position is None
                or (leg.position_date == "TODAY" and row.today_position != row.position)
                or (leg.position_date == "HISTORY" and row.today_position != 0)
                or any(
                    getattr(row, name) is None or getattr(row, name) != 0 for name in freeze_values
                )
            ):
                return (), "DATED_CLOSE_INVENTORY_ROW_INVALID"
        provider_quantity = sum((row.position for row in rows), Decimal(0))
        quantity = _exact_hands(leg.available_quantity)
        if (
            leg.provider_quantity != provider_quantity
            or leg.owned_quantity != provider_quantity
            or leg.available_quantity != provider_quantity
            or quantity is None
            or quantity <= 0
        ):
            return (), "DATED_CLOSE_QUANTITY_MISMATCH"

        lots = tuple(leg.lots)
        opening_execution_ids = tuple(leg.opening_execution_ids)
        if not lots or any(
            not item.execution_id
            or not item.intent_id
            or not item.open_observation_id
            or not item.open_snapshot_id
            or not item.open_query_set_id
            or item.owner_intent_id != leg.owner_intent_id
            or item.strategy_scope != inputs.strategy_scope
            or item.position_side != leg.position_side
            or item.hedge_flag != leg.hedge_flag
            or item.trading_day is None
            or item.remaining_quantity is None
            or item.remaining_quantity <= 0
            or item.opened_quantity is None
            or item.closed_quantity is None
            or item.opened_quantity <= 0
            or item.closed_quantity < 0
            or item.opened_quantity - item.closed_quantity != item.remaining_quantity
            or (leg.position_date == "TODAY" and item.trading_day != inputs.dated_trading_day)
            or (leg.position_date == "HISTORY" and item.trading_day >= inputs.dated_trading_day)
            for item in lots
        ):
            return (), "DATED_CLOSE_OPENING_LOT_PROOF_INVALID"
        if (
            sum((item.remaining_quantity for item in lots), Decimal(0)) != provider_quantity
            or len(set(opening_execution_ids)) != len(opening_execution_ids)
            or set(opening_execution_ids)
            != {item.execution_id for item in lots if item.execution_id is not None}
            or any(item.execution_id is None for item in lots)
        ):
            return (), "DATED_CLOSE_OPENING_LOT_QUANTITY_MISMATCH"

        total_quantity += quantity
        actions.append(
            Alpha003OrderAction(
                action="SUBMIT",
                target_id=position.target_id,
                instrument=position.instrument,
                side=side,
                position_effect="CLOSE",
                quantity=quantity,
                limit_price=limit_price,
                offset=leg.offset,
                reason=reason,
                owner_intent_id=position.owner_intent_id,
                exchange=position.exchange,
                decision_available_at=inputs.evaluated_at,
                position_side=leg.position_side.lower(),
                dated_position_side=leg.position_side,
                position_date=leg.position_date,
                offset_flag=leg.offset_flag,
                hedge_flag=leg.hedge_flag,
                dated_query_set_id=leg.query_set_id,
                dated_snapshot_id=leg.snapshot_id,
                dated_account_fingerprint=leg.account_fingerprint,
                dated_connection_generation=leg.connection_generation,
                dated_trading_day=leg.trading_day,
                dated_available_at=leg.available_at,
                dated_source_row_ids=source_ids,
                dated_opening_execution_ids=opening_execution_ids,
                dated_close_execution_ids=tuple(leg.close_execution_ids),
            )
        )
    if total_quantity != abs(position.quantity):
        return (), "DATED_CLOSE_TOTAL_POSITION_MISMATCH"
    return tuple(actions), None


def _decimal_number(value: Any, label: str) -> Decimal:
    if isinstance(value, bool) or value is None:
        raise ValueError("{} must be a finite decimal number".format(label))
    try:
        number = value if isinstance(value, Decimal) else Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        raise ValueError("{} must be a finite decimal number".format(label)) from None
    if not number.is_finite():
        raise ValueError("{} must be a finite decimal number".format(label))
    return number


def _next_float(value: float, *, upward: bool) -> float:
    """Return the adjacent IEEE-754 double, including on supported Python 3.8."""

    nextafter = getattr(math, "nextafter", None)
    if callable(nextafter):
        return nextafter(value, math.inf if upward else -math.inf)
    bits = struct.unpack(">Q", struct.pack(">d", value))[0]
    if value == 0.0:
        bits = 1 if upward else (1 << 63) | 1
    elif (value > 0) == upward:
        bits += 1
    else:
        bits -= 1
    return struct.unpack(">d", struct.pack(">Q", bits))[0]


def _risk_native_float_envelope(
    value: Any, *, upward: bool, allow_negative: bool = False
) -> Optional[Decimal]:
    """Keep exact decimal inputs and envelope an observed native float by one ULP.

    This bounds arithmetic around the float received by Python. It does not
    recover or prove the provider's original economic decimal representation.
    """

    if type(value) is float:
        if not math.isfinite(value):
            return None
        # Reject a negative observed value before rounding it to an adjacent
        # float. The least negative subnormal rounds upward to -0.0, which
        # otherwise passes the downstream non-negative Decimal check.
        if not allow_negative and value < 0.0:
            return None
        if value != 0.0:
            value = _next_float(value, upward=upward)
        number = Decimal.from_float(value)
    else:
        try:
            number = _decimal_number(value, "risk value")
        except (TypeError, ValueError):
            return None
    return _risk_decimal_operand(number, allow_negative=allow_negative)


def _positive_decimal(value: Any, label: str) -> Decimal:
    number = _decimal_number(value, label)
    if number <= 0:
        raise ValueError("{} must be positive".format(label))
    return number


def _freshness_seconds(value: Any, label: str, *, allow_zero: bool = False) -> float:
    if type(value) not in (int, float) or not math.isfinite(value):
        raise TypeError("%s must be a finite built-in real number" % label)
    if value < 0 or (value == 0 and not allow_zero):
        comparator = "non-negative" if allow_zero else "positive"
        raise ValueError("%s must be %s" % (label, comparator))
    return float(value)


def _nonnegative_decimal(value: Any, label: str) -> Decimal:
    number = _decimal_number(value, label)
    if number < 0:
        raise ValueError("{} must be non-negative".format(label))
    return number


_RISK_DECIMAL_MAX_DIGITS = 128
_RISK_DECIMAL_MAX_EXPONENT = 128
_RISK_DECIMAL_MAX_ADJUSTED_EXPONENT = 255
_RISK_DECIMAL_CONTEXT_PRECISION = 2048


def _risk_decimal_operand(value: Any, *, allow_negative: bool = False) -> Optional[Decimal]:
    """Return a bounded non-negative Decimal suitable for risk arithmetic.

    CTP/native facts and operator configuration are external inputs.  Cap both
    coefficient length and exponent before doing risk math so an extreme value
    cannot cause unbounded work or overflow the directed-rounding context.
    """

    if type(value) is int:
        if (not allow_negative and value < 0) or value.bit_length() > 426:
            return None
        number = Decimal(value)
    elif type(value) is Decimal:
        number = value
    else:
        return None
    if not number.is_finite() or (not allow_negative and number < 0):
        return None
    parts = number.as_tuple()
    if (
        len(parts.digits) > _RISK_DECIMAL_MAX_DIGITS
        or type(parts.exponent) is not int
        or abs(parts.exponent) > _RISK_DECIMAL_MAX_EXPONENT
        or (not number.is_zero() and abs(number.adjusted()) > _RISK_DECIMAL_MAX_ADJUSTED_EXPONENT)
    ):
        return None
    return number


def _risk_ceiling_product(*values: Any) -> Optional[Decimal]:
    """Multiply bounded non-negative operands with directed upper rounding."""

    operands = tuple(_risk_decimal_operand(value) for value in values)
    if not operands or any(value is None for value in operands):
        return None
    try:
        with localcontext() as context:
            context.prec = _RISK_DECIMAL_CONTEXT_PRECISION
            context.Emax = 1024
            context.Emin = -1024
            context.rounding = ROUND_CEILING
            result = operands[0]
            for value in operands[1:]:
                result *= value
    except DecimalException:
        return None
    return _risk_decimal_operand(result)


def _risk_ceiling_sum(*values: Any) -> Optional[Decimal]:
    """Add bounded non-negative operands with directed upper rounding."""

    operands = tuple(_risk_decimal_operand(value) for value in values)
    if not operands or any(value is None for value in operands):
        return None
    try:
        with localcontext() as context:
            context.prec = _RISK_DECIMAL_CONTEXT_PRECISION
            context.Emax = 1024
            context.Emin = -1024
            context.rounding = ROUND_CEILING
            result = sum(operands, Decimal(0))
    except DecimalException:
        return None
    return _risk_decimal_operand(result)


def _risk_stop_price(price: Any, distance: Any, side: str) -> Optional[Decimal]:
    price_number = _risk_decimal_operand(price)
    distance_number = _risk_decimal_operand(distance)
    if (
        price_number is None
        or distance_number is None
        or side not in {"BUY", "SELL"}
    ):
        return None
    try:
        with localcontext() as context:
            context.prec = _RISK_DECIMAL_CONTEXT_PRECISION
            context.Emax = 1024
            context.Emin = -1024
            context.rounding = ROUND_CEILING
            result = (
                price_number - distance_number
                if side == "BUY"
                else price_number + distance_number
            )
    except DecimalException:
        return None
    return _risk_decimal_operand(result, allow_negative=True)


def _state_is_fresh(available_at: datetime, evaluated_at: datetime, maximum_age: Decimal) -> bool:
    if not isinstance(available_at, datetime):
        return False
    age = Decimal(str((evaluated_at - available_at).total_seconds()))
    return age >= 0 and age <= maximum_age


def _price_is_on_tick(value: Decimal, tick: Decimal) -> bool:
    price = _risk_decimal_operand(value, allow_negative=True)
    tick_size = _risk_decimal_operand(tick)
    if price is None or tick_size is None or tick_size == 0:
        return False
    try:
        with localcontext() as context:
            context.prec = _RISK_DECIMAL_CONTEXT_PRECISION
            context.Emax = 1024
            context.Emin = -1024
            context.rounding = ROUND_CEILING
            remainder = price % tick_size
    except DecimalException:
        return False
    return remainder == 0


def _quote_for_order(
    quote: Alpha003QuoteFact,
    risk: Alpha003InstrumentRiskFact,
    *,
    side: str,
    after: datetime,
    evaluated_at: datetime,
    max_age: Decimal,
) -> Optional[Decimal]:
    if (
        quote.metadata_snapshot_id is None
        or quote.event_time is None
        or quote.available_at is None
        or quote.bid is None
        or quote.ask is None
        or quote.tick_size is None
        or quote.lower_limit is None
        or quote.upper_limit is None
        or quote.instrument != risk.instrument
        or (risk.exchange is not None and quote.exchange != risk.exchange)
        or quote.metadata_snapshot_id != risk.snapshot_id
        or quote.quality != "GOOD"
        or quote.event_time < after
        or quote.available_at < after
        or quote.available_at < quote.event_time
        or quote.available_at > evaluated_at
        or not _state_is_fresh(quote.available_at, evaluated_at, max_age)
        or quote.bid > quote.ask
        or quote.lower_limit > quote.upper_limit
        or not all(
            _price_is_on_tick(value, quote.tick_size)
            for value in (quote.bid, quote.ask, quote.lower_limit, quote.upper_limit)
        )
        or quote.bid < quote.lower_limit
        or quote.ask > quote.upper_limit
    ):
        return None
    if quote.evidence_source == "REPLAY_TAPE":
        if quote.source_ref is None:
            return None
    elif quote.bid_size is None or quote.ask_size is None:
        return None
    bid_depth_lower = (
        quote.risk_bid_size_lower
        if quote.risk_bid_size_lower is not None
        else quote.bid_size
    )
    ask_depth_lower = (
        quote.risk_ask_size_lower
        if quote.risk_ask_size_lower is not None
        else quote.ask_size
    )
    if side == "BUY":
        if (
            quote.evidence_source != "REPLAY_TAPE"
            and ask_depth_lower is not None
            and ask_depth_lower < Decimal(1)
        ):
            return None
        return quote.ask
    if side == "SELL":
        if (
            quote.evidence_source != "REPLAY_TAPE"
            and bid_depth_lower is not None
            and bid_depth_lower < Decimal(1)
        ):
            return None
        return quote.bid
    return None


def _execution_route_authorized(
    inputs: Alpha003OrderPlanningInput,
    target_id: Optional[str],
    *,
    instrument: Optional[str] = None,
    exchange: Optional[str] = None,
) -> bool:
    """Check the grant and that target's own route before emitting an action."""

    if inputs.execution_target_ids is None:
        return True
    if target_id is None or target_id not in inputs.execution_target_ids:
        return False
    matches = tuple(item for item in inputs.instruments if item.target_id == target_id)
    if len(matches) != 1 or matches[0].route_permitted is not True:
        return False
    route = matches[0]
    if instrument is not None and route.instrument != instrument:
        return False
    if exchange is not None and route.exchange != exchange:
        return False
    return True


def plan_alpha003_orders(inputs: Alpha003OrderPlanningInput) -> Alpha003OrderPlan:
    """Plan closes/cancels before opening, from exact actual fact projections.

    Risk-reduction readiness and new-risk readiness remain separate. Missing
    capital/margin facts therefore blocks a new hand without suppressing a
    validated stop, hold, session, run-end, or target-change reduction.
    """

    if not isinstance(inputs, Alpha003OrderPlanningInput):
        raise TypeError("inputs must be Alpha003OrderPlanningInput")
    policy = inputs.risk_policy
    target = inputs.target_decision
    expected_execution_mode = "LIVE" if inputs.evidence_source == "REGISTERED_SIM" else "REPLAY"
    expected_quote_source = (
        "REGISTERED_SIM" if inputs.evidence_source == "REGISTERED_SIM" else "REPLAY_TAPE"
    )
    account_snapshot_id = inputs.account.snapshot_id if inputs.account is not None else None

    def blocked(reason: str) -> Alpha003OrderPlan:
        return Alpha003OrderPlan(
            "BLOCKED",
            reason,
            (),
            target.batch_id if target is not None else None,
            inputs.evaluated_at,
            account_snapshot_id,
        )

    def completed(
        status: str,
        reason: Optional[str],
        actions=(),
        open_risk_candidate: Optional[Alpha003OpenRiskCandidate] = None,
    ) -> Alpha003OrderPlan:
        return Alpha003OrderPlan(
            status,
            reason,
            tuple(actions),
            target.batch_id if target is not None else None,
            inputs.evaluated_at,
            account_snapshot_id,
            open_risk_candidate,
        )

    if policy is None:
        return blocked("RISK_POLICY_REQUIRED")
    if inputs.risk_evidence_available_at is None:
        return blocked("RISK_EVIDENCE_UNAVAILABLE")
    if inputs.evaluated_at < inputs.risk_evidence_available_at:
        return blocked("RISK_EVIDENCE_FROM_FUTURE")

    target_candidate = target is not None and target.status == "TARGETS_READY"
    target_ready = bool(
        target_candidate
        and target.execution_mode == expected_execution_mode
        and target.available_at >= target.close_time
        and _state_is_fresh(target.available_at, inputs.evaluated_at, policy.max_state_age_seconds)
    )
    if target_candidate and target.execution_mode != expected_execution_mode:
        return blocked("TARGET_EXECUTION_MODE_MISMATCH")
    if target_candidate and target.available_at > inputs.evaluated_at:
        return blocked("TARGET_AVAILABILITY_INVALID")

    if inputs.execution_target_ids is not None:
        position_ids = tuple(item.target_id for item in inputs.positions)
        instrument_ids = tuple(item.target_id for item in inputs.instruments)
        if (
            any(target_id is None for target_id in position_ids)
            or len(set(position_ids)) != len(position_ids)
            or len(set(instrument_ids)) != len(instrument_ids)
            or set(position_ids) != set(instrument_ids)
            or not set(inputs.execution_target_ids).issubset(set(position_ids))
        ):
            return blocked("EXECUTION_FACT_SET_INVALID")
        authorized_targets = set(inputs.execution_target_ids)
        if any(
            position.target_id not in authorized_targets
            and (position.quantity is None or position.quantity != 0)
            for position in inputs.positions
        ):
            return blocked("UNAUTHORIZED_POSITION_SCOPE")
        if any(order.target_id not in authorized_targets for order in inputs.working_orders):
            return blocked("UNAUTHORIZED_WORKING_ORDER_SCOPE")

    preclose = bool(
        inputs.session_close_at is not None
        and inputs.evaluated_at
        >= inputs.session_close_at - timedelta(seconds=policy.preclose_grace_seconds)
    )
    exit_window_reason = "RUN_END" if inputs.run_end else "PRE_CLOSE" if preclose else None
    if exit_window_reason is not None:
        # Cancelling an owned opening order needs a complete, exact order
        # projection but no quote, position mark, or account capacity. Keep
        # this as its own readiness check so shutdown can stop pending entries
        # during a market gap while CLOSE remains guarded by risk readiness.
        cancel_actions = []
        unresolved_exit_order = False
        for order in inputs.working_orders:
            if order.position_effect not in ("OPEN", "CLOSE"):
                return blocked("WORKING_ORDER_FIELDS_UNAVAILABLE")
            if order.owner_strategy_scope != inputs.strategy_scope or not order.owner_intent_id:
                return blocked("UNOWNED_WORKING_ORDER")
            if order.target_id is None or order.exchange is None or order.side is None:
                return blocked("WORKING_ORDER_FIELDS_UNAVAILABLE")
            if order.remaining_quantity is None or order.remaining_quantity < 1:
                return blocked("WORKING_ORDER_QUANTITY_INVALID")
            if order.state not in {
                "PREPARED",
                "DISPATCHING",
                "UNKNOWN",
                "CANCEL_PENDING",
                "ACCEPTED",
                "PARTIAL",
            }:
                return blocked("WORKING_ORDER_STATE_UNKNOWN")
            if order.position_effect == "CLOSE":
                unresolved_exit_order = True
                continue
            if order.state in {"PREPARED", "DISPATCHING", "UNKNOWN", "CANCEL_PENDING"}:
                unresolved_exit_order = True
                continue
            if not _execution_route_authorized(
                inputs,
                order.target_id,
                instrument=order.instrument,
                exchange=order.exchange,
            ):
                return blocked("ORDER_CANCEL_ROUTE_NOT_AUTHORIZED")
            if not inputs.order_cancel_ready:
                detail = (
                    ":" + inputs.order_cancel_blockers[0] if inputs.order_cancel_blockers else ""
                )
                return blocked("ORDER_CANCEL_FACTS_UNAVAILABLE" + detail)
            cancel_actions.append(
                Alpha003OrderAction(
                    action="CANCEL",
                    target_id=order.target_id,
                    instrument=order.instrument,
                    side=order.side,
                    position_effect="OPEN",
                    quantity=order.remaining_quantity,
                    limit_price=None,
                    offset="open",
                    reason=exit_window_reason + "_CANCEL_PENDING_OPEN",
                    order_ref=order.order_ref,
                    owner_intent_id=order.owner_intent_id,
                    exchange=order.exchange,
                    decision_available_at=inputs.evaluated_at,
                    broker_order_ref=order.broker_order_ref,
                )
            )
        if cancel_actions:
            if len(cancel_actions) > policy.max_order_intents_per_grid:
                return blocked("ORDER_INTENT_BUDGET_EXCEEDED")
            if inputs.run_order_intents_used is None:
                return blocked("RUN_ORDER_BUDGET_UNAVAILABLE")
            reserve_after_plan = _future_exit_intent_reserve(
                inputs, planned_actions=tuple(cancel_actions)
            )
            if (
                inputs.run_order_intents_used + len(cancel_actions) + reserve_after_plan
                > policy.max_order_intents_per_run
            ):
                return blocked("RUN_ORDER_BUDGET_EXCEEDED")
            return completed("READY", "CANCEL_OPEN_ORDERS_BEFORE_EXIT", cancel_actions)
        if unresolved_exit_order:
            return blocked("EXIT_ORDER_TERMINAL_EVIDENCE_PENDING")

    positions_by_target = {item.target_id: item for item in inputs.positions}
    instruments_by_target = {item.target_id: item for item in inputs.instruments}
    if (
        not positions_by_target
        or len(positions_by_target) != len(inputs.positions)
        or len(instruments_by_target) != len(inputs.instruments)
        or set(positions_by_target) != set(instruments_by_target)
    ):
        return blocked("EXECUTION_FACT_SET_INVALID")
    if any(item.target_id is None for item in inputs.positions):
        return blocked("POSITION_OUTSIDE_TARGET_SCOPE")
    if any(item.quantity is None for item in inputs.positions):
        return blocked("POSITION_QUANTITY_UNAVAILABLE")
    if any(
        item.instrument != instruments_by_target[item.target_id].instrument
        or item.exchange != instruments_by_target[item.target_id].exchange
        or item.exchange is None
        for item in inputs.positions
    ):
        return blocked("POSITION_INSTRUMENT_IDENTITY_MISMATCH")

    quotes_by_key = {}
    for quote in inputs.quotes:
        if quote.exchange is None:
            return blocked("QUOTE_EXCHANGE_UNAVAILABLE")
        key = (quote.instrument, quote.exchange)
        if key in quotes_by_key or quote.evidence_source != expected_quote_source:
            return blocked("QUOTE_FACT_SET_INVALID")
        quotes_by_key[key] = quote

    by_instrument = {}
    for order in inputs.working_orders:
        if order.exchange is None:
            return blocked("WORKING_ORDER_EXCHANGE_UNAVAILABLE")
        key = (order.instrument, order.exchange)
        by_instrument.setdefault(key, []).append(order)
    if any(len(orders) > 1 for orders in by_instrument.values()):
        return blocked("MULTIPLE_WORKING_ORDERS_PER_INSTRUMENT")
    unresolved_states = {"PREPARED", "DISPATCHING", "UNKNOWN", "CANCEL_PENDING"}
    for order in inputs.working_orders:
        if order.side is None or order.position_effect is None or order.remaining_quantity is None:
            return blocked("WORKING_ORDER_FIELDS_UNAVAILABLE")
        if order.owner_strategy_scope != inputs.strategy_scope or not order.owner_intent_id:
            return blocked("UNOWNED_WORKING_ORDER")
        if order.remaining_quantity < 1:
            return blocked("WORKING_ORDER_QUANTITY_INVALID")
        if order.state not in unresolved_states | {"ACCEPTED", "PARTIAL"}:
            return blocked("WORKING_ORDER_STATE_UNKNOWN")

    if any(
        item.available_at is None
        or not _state_is_fresh(item.available_at, inputs.evaluated_at, policy.max_state_age_seconds)
        for item in inputs.positions
    ) or any(
        item.available_at is None
        or not _state_is_fresh(item.available_at, inputs.evaluated_at, policy.max_state_age_seconds)
        for item in inputs.instruments
    ):
        return blocked("POSITION_OR_METADATA_STALE")

    open_positions = []
    for position in inputs.positions:
        if position.quantity == 0:
            continue
        if position.owner_strategy_scope != inputs.strategy_scope or not position.owner_intent_id:
            return blocked("UNOWNED_POSITION")
        if abs(position.quantity) > 1:
            return blocked("POSITION_EXCEEDS_ONE_HAND")
        open_positions.append(position)
    if len({(item.instrument, item.exchange) for item in open_positions}) > 2:
        return blocked("POSITION_LIMIT_EXCEEDED")

    if inputs.risk_reduction_blockers:
        return blocked("RISK_REDUCTION_FACTS_BLOCKED:" + inputs.risk_reduction_blockers[0])
    if not inputs.risk_reduction_ready:
        return blocked("RISK_REDUCTION_FACTS_UNAVAILABLE")
    account = inputs.account

    active_by_instrument = {key: orders[0] for key, orders in by_instrument.items()}
    target_by_id = {item.target_id: item for item in target.targets} if target_ready else {}
    reduce_actions = []
    has_due_exit = False
    target_after = target.available_at if target_ready else inputs.risk_evidence_available_at
    for position in open_positions:
        risk = instruments_by_target[position.target_id]
        instrument_key = (position.instrument, position.exchange)
        quote = quotes_by_key.get(instrument_key)
        stop_hit = False
        if (
            position.stop_price is not None
            and quote is not None
            and quote.quality == "GOOD"
            and quote.bid is not None
            and quote.ask is not None
        ):
            stop_hit = (position.quantity > 0 and quote.bid <= position.stop_price) or (
                position.quantity < 0 and quote.ask >= position.stop_price
            )
        held_due = (
            position.held_eligible_bars is not None
            and position.held_eligible_bars >= policy.max_hold_eligible_bars
        )
        desired = target_by_id.get(position.target_id)
        target_changed = target_ready and (
            desired is None or desired.target_position != (1 if position.quantity > 0 else -1)
        )
        reason = (
            "RUN_END"
            if inputs.run_end and policy.run_end_policy == "CLOSE_ALL"
            else "PRE_CLOSE"
            if preclose
            else "STOP_LOSS"
            if stop_hit
            else "MAX_HOLD"
            if held_due
            else "TARGET_REBALANCE"
            if target_changed
            else None
        )
        active = active_by_instrument.get(instrument_key)
        if active is not None:
            if active.state in unresolved_states or active.position_effect == "CLOSE":
                has_due_exit = has_due_exit or reason is not None
                continue
            if reason is None:
                continue
            if not _execution_route_authorized(
                inputs,
                active.target_id,
                instrument=position.instrument,
                exchange=position.exchange,
            ):
                return blocked("ORDER_CANCEL_ROUTE_NOT_AUTHORIZED")
            if inputs.execution_target_ids is not None and not inputs.order_cancel_ready:
                detail = (
                    ":" + inputs.order_cancel_blockers[0] if inputs.order_cancel_blockers else ""
                )
                return blocked("ORDER_CANCEL_FACTS_UNAVAILABLE" + detail)
            if active.state not in {"ACCEPTED", "PARTIAL"}:
                return blocked("OPEN_ORDER_NOT_CANCELLABLE")
            reduce_actions.append(
                Alpha003OrderAction(
                    action="CANCEL",
                    target_id=position.target_id,
                    instrument=position.instrument,
                    side=active.side,
                    position_effect="OPEN",
                    quantity=active.remaining_quantity,
                    limit_price=None,
                    offset="open",
                    reason="CANCEL_OPEN_BEFORE_REDUCTION:" + reason,
                    order_ref=active.order_ref,
                    owner_intent_id=active.owner_intent_id,
                    exchange=position.exchange,
                    decision_available_at=inputs.evaluated_at,
                    broker_order_ref=active.broker_order_ref,
                )
            )
            has_due_exit = True
            continue
        has_due_exit = has_due_exit or reason is not None
        if reason is None:
            continue
        close_side = "SELL" if position.quantity > 0 else "BUY"
        if not _execution_route_authorized(
            inputs,
            position.target_id,
            instrument=position.instrument,
            exchange=position.exchange,
        ):
            return blocked("REDUCTION_ROUTE_NOT_AUTHORIZED")
        if risk.trading_permitted is not True or risk.route_permitted is not True or quote is None:
            continue
        limit_price = _quote_for_order(
            quote,
            risk,
            side=close_side,
            after=target_after,
            evaluated_at=inputs.evaluated_at,
            max_age=policy.quote_max_age_seconds,
        )
        if limit_price is None:
            continue
        if position.exchange in {"SHFE", "INE"}:
            dated_actions, dated_error = _dated_close_actions_for_position(
                inputs,
                position,
                side=close_side,
                limit_price=limit_price,
                reason=reason,
            )
            if dated_error is not None:
                return blocked(dated_error)
            reduce_actions.extend(dated_actions)
        else:
            reduce_actions.append(
                Alpha003OrderAction(
                    action="SUBMIT",
                    target_id=position.target_id,
                    instrument=position.instrument,
                    side=close_side,
                    position_effect="CLOSE",
                    quantity=abs(position.quantity),
                    limit_price=limit_price,
                    offset="close",
                    reason=reason,
                    owner_intent_id=position.owner_intent_id,
                    exchange=position.exchange,
                    decision_available_at=inputs.evaluated_at,
                )
            )

    # A flat Broker position does not prove that an accepted opening order is
    # terminal. At preclose/run-end, cancel every Strategy-owned pending OPEN
    # before the Strategy can leave the execution loop. This also covers a
    # partially filled order whose current projected position is momentarily
    # flat because the remaining fill has not yet reached the position view.
    if exit_window_reason is not None:
        planned_cancel_refs = {
            action.order_ref for action in reduce_actions if action.action == "CANCEL"
        }
        for order in inputs.working_orders:
            position = positions_by_target.get(order.target_id)
            if (
                order.position_effect != "OPEN"
                or position is None
                or position.quantity != 0
                or order.order_ref in planned_cancel_refs
            ):
                continue
            if order.state in unresolved_states:
                has_due_exit = True
                continue
            if order.state not in {"ACCEPTED", "PARTIAL"}:
                return blocked("OPEN_ORDER_NOT_CANCELLABLE")
            if not _execution_route_authorized(
                inputs,
                order.target_id,
                instrument=order.instrument,
                exchange=order.exchange,
            ):
                return blocked("ORDER_CANCEL_ROUTE_NOT_AUTHORIZED")
            if inputs.execution_target_ids is not None and not inputs.order_cancel_ready:
                detail = (
                    ":" + inputs.order_cancel_blockers[0] if inputs.order_cancel_blockers else ""
                )
                return blocked("ORDER_CANCEL_FACTS_UNAVAILABLE" + detail)
            reduce_actions.append(
                Alpha003OrderAction(
                    action="CANCEL",
                    target_id=order.target_id,
                    instrument=order.instrument,
                    side=order.side,
                    position_effect="OPEN",
                    quantity=order.remaining_quantity,
                    limit_price=None,
                    offset="open",
                    reason=exit_window_reason + "_CANCEL_PENDING_OPEN",
                    order_ref=order.order_ref,
                    owner_intent_id=order.owner_intent_id,
                    exchange=order.exchange,
                    decision_available_at=inputs.evaluated_at,
                    broker_order_ref=order.broker_order_ref,
                )
            )
            planned_cancel_refs.add(order.order_ref)
            has_due_exit = True

        # A close already in flight against a now-flat projection is still
        # active execution state. Let its terminal callback/reconciliation
        # settle before declaring the exit window clear.
        for order in inputs.working_orders:
            position = positions_by_target.get(order.target_id)
            if (
                order.position_effect == "CLOSE"
                and position is not None
                and position.quantity == 0
                and order.state in unresolved_states | {"ACCEPTED", "PARTIAL"}
            ):
                has_due_exit = True

    if reduce_actions:
        if len(reduce_actions) > policy.max_order_intents_per_grid:
            return blocked("ORDER_INTENT_BUDGET_EXCEEDED")
        if inputs.run_order_intents_used is None:
            return blocked("RUN_ORDER_BUDGET_UNAVAILABLE")
        reserve_after_plan = _future_exit_intent_reserve(
            inputs, planned_actions=tuple(reduce_actions)
        )
        if (
            inputs.run_order_intents_used + len(reduce_actions) + reserve_after_plan
            > policy.max_order_intents_per_run
        ):
            return blocked("RUN_ORDER_BUDGET_EXCEEDED")
        return completed("READY", "REDUCTIONS_BEFORE_INCREASES", reduce_actions)
    if has_due_exit:
        return blocked("RISK_REDUCTION_WAITING_FOR_TERMINAL_POSITION_EVIDENCE")

    if (
        inputs.session_close_at is not None
        and inputs.session_close_at <= inputs.evaluated_at
        and not inputs.run_end
    ):
        return completed("NO_ACTION", "SESSION_CLOSED")

    # Missing opening capital/routing facts do not erase the reduction path
    # above. They must independently qualify every increase.
    if not target_ready:
        return completed("NO_ACTION", "NO_FRESH_TARGET")
    if inputs.run_end or preclose:
        return completed("NO_ACTION", "EXIT_WINDOW")
    if inputs.session_close_at is None:
        return blocked("SESSION_CLOSE_UNKNOWN")
    if account is None:
        return blocked("ACCOUNT_RISK_UNAVAILABLE")
    if not _state_is_fresh(account.available_at, inputs.evaluated_at, policy.max_state_age_seconds):
        return blocked("ACCOUNT_RISK_STALE")
    if account.route_permitted is not True:
        return blocked("ROUTE_NOT_AUTHORIZED")
    for position in open_positions:
        quote = quotes_by_key.get((position.instrument, position.exchange))
        close_side = "SELL" if position.quantity > 0 else "BUY"
        if (
            quote is None
            or _quote_for_order(
                quote,
                instruments_by_target[position.target_id],
                side=close_side,
                after=target.available_at,
                evaluated_at=inputs.evaluated_at,
                max_age=policy.quote_max_age_seconds,
            )
            is None
        ):
            return blocked("OPEN_POSITION_QUOTE_UNAVAILABLE")
    if inputs.open_risk_blockers:
        return blocked("OPEN_RISK_FACTS_BLOCKED:" + inputs.open_risk_blockers[0])
    if not inputs.open_risk_ready:
        return blocked("OPEN_RISK_FACTS_UNAVAILABLE")
    if inputs.execution_blockers:
        return blocked("EXECUTION_FACTS_BLOCKED:" + inputs.execution_blockers[0])
    if any(order.state in unresolved_states for order in inputs.working_orders):
        return blocked("UNRESOLVED_INTENT_BLOCKS_NEW_RISK")
    for order in inputs.working_orders:
        if order.position_effect != "OPEN" or order.state not in {"ACCEPTED", "PARTIAL"}:
            continue
        position = positions_by_target[order.target_id]
        held_quantity = abs(position.quantity or 0)
        if held_quantity + order.remaining_quantity > 1:
            return blocked("WORKING_OPEN_EXCEEDS_ONE_HAND")
    if any(
        position.quantity != 0 and position.held_eligible_bars is None
        for position in inputs.positions
    ):
        return blocked("HOLDING_AGE_UNAVAILABLE")
    if any(
        value is None
        for value in (
            account.available_margin,
            account.used_margin,
            account.current_notional,
            account.current_worst_case_loss,
        )
    ):
        return blocked("ACCOUNT_RISK_BUDGET_UNAVAILABLE")
    if any(
        _risk_decimal_operand(value) is None
        for value in (
            policy.max_notional_per_position,
            policy.max_total_notional,
            policy.max_margin_per_position,
            policy.max_total_margin,
            policy.max_loss_per_position,
            policy.max_total_loss,
            account.available_margin,
            account.used_margin,
            account.current_notional,
            account.current_worst_case_loss,
        )
    ):
        return blocked("RISK_ARITHMETIC_VALUE_OUT_OF_RANGE")

    desired_open = []
    for signal in target.targets:
        if not _execution_route_authorized(
            inputs,
            signal.target_id,
            instrument=(
                positions_by_target[signal.target_id].instrument
                if signal.target_id in positions_by_target
                else None
            ),
            exchange=(
                positions_by_target[signal.target_id].exchange
                if signal.target_id in positions_by_target
                else None
            ),
        ):
            return blocked("OPEN_TARGET_ROUTE_NOT_AUTHORIZED")
        position = positions_by_target.get(signal.target_id)
        if position is None:
            return blocked("TARGET_POSITION_SNAPSHOT_MISSING")
        current_sign = 1 if position.quantity > 0 else -1 if position.quantity < 0 else 0
        if current_sign == signal.target_position:
            continue
        if current_sign != 0:
            return blocked("REDUCTION_REQUIRED_BEFORE_REVERSAL")
        key = (position.instrument, position.exchange)
        if key in active_by_instrument:
            order = active_by_instrument[key]
            if order.position_effect == "OPEN" and order.side == (
                "BUY" if signal.target_position > 0 else "SELL"
            ):
                continue
            return blocked("WORKING_ORDER_BLOCKS_TARGET")
        desired_open.append(signal)
    if not desired_open:
        return completed("NO_ACTION", "TARGETS_ALREADY_HELD_OR_PENDING")

    live_commission_sidecar_required = bool(
        inputs.evidence_source == "REGISTERED_SIM"
        and any(item.commission_fee_required for item in inputs.instruments)
    )
    fee_bounds_by_target = {}
    for signal in desired_open:
        risk = instruments_by_target[signal.target_id]
        fee_bound = risk.round_trip_fee_upper_bound_per_contract
        if live_commission_sidecar_required or risk.commission_fee_required:
            # LIVE fees are fail-closed per selected target. A static policy
            # reserve cannot override a missing, stale, ambiguous, or otherwise
            # unproven sidecar result. Preserve Alpha003's paired high/low
            # rebalance: either every selected OPEN is fee-qualified or none is.
            if risk.commission_fee_status != "AVAILABLE" or fee_bound is None:
                return blocked("ROUND_TRIP_FEE_BUDGET_UNAVAILABLE")
        elif fee_bound is None:
            fee_bound = policy.round_trip_fee_upper_bound_per_contract
        elif policy.round_trip_fee_upper_bound_per_contract is not None:
            fee_bound = max(fee_bound, policy.round_trip_fee_upper_bound_per_contract)
        if fee_bound is None:
            return blocked("ROUND_TRIP_FEE_BUDGET_UNAVAILABLE")
        fee_bounds_by_target[signal.target_id] = fee_bound
    current_count = len(open_positions) + sum(
        1
        for order in inputs.working_orders
        if order.position_effect == "OPEN" and order.state in ("ACCEPTED", "PARTIAL")
    )
    if current_count + len(desired_open) > 2:
        return blocked("MAX_OPEN_INSTRUMENTS")

    held_fee_reserve = Decimal(0)
    for position in open_positions:
        risk = instruments_by_target.get(position.target_id)
        fee_bound = (
            risk.round_trip_fee_upper_bound_per_contract if risk is not None else None
        )
        if live_commission_sidecar_required or (
            risk is not None and risk.commission_fee_required
        ):
            if (
                risk is None
                or risk.commission_fee_status != "AVAILABLE"
                or fee_bound is None
            ):
                return blocked("ROUND_TRIP_FEE_BUDGET_UNAVAILABLE")
        elif fee_bound is None:
            fee_bound = policy.round_trip_fee_upper_bound_per_contract
        elif policy.round_trip_fee_upper_bound_per_contract is not None:
            fee_bound = max(fee_bound, policy.round_trip_fee_upper_bound_per_contract)
        if fee_bound is None:
            return blocked("ROUND_TRIP_FEE_BUDGET_UNAVAILABLE")
        # Both operands are non-negative.  Use bounded directed arithmetic so
        # a many-digit native fee cannot round down before reaching a cap.
        held_fee = _risk_ceiling_product(abs(position.quantity), fee_bound)
        if held_fee is None:
            return blocked("RISK_ARITHMETIC_VALUE_OUT_OF_RANGE")
        held_fee_reserve = _risk_ceiling_sum(held_fee_reserve, held_fee)
        if held_fee_reserve is None:
            return blocked("RISK_ARITHMETIC_VALUE_OUT_OF_RANGE")

    open_actions = []
    open_risk_legs = []
    required_margin = Decimal(0)
    added_notional = Decimal(0)
    added_loss = Decimal(0)
    for signal in desired_open:
        position = positions_by_target[signal.target_id]
        risk = instruments_by_target[signal.target_id]
        fee_bound = fee_bounds_by_target[signal.target_id]
        multiplier_upper = risk.risk_multiplier_upper
        long_margin_upper = risk.risk_long_margin_per_hand_upper
        short_margin_upper = risk.risk_short_margin_per_hand_upper
        if (
            multiplier_upper is None
            or long_margin_upper is None
            or short_margin_upper is None
        ):
            if any(
                source is not None and bound is None
                for source, bound in (
                    (risk.multiplier, multiplier_upper),
                    (risk.long_margin_per_hand, long_margin_upper),
                    (risk.short_margin_per_hand, short_margin_upper),
                )
            ):
                return blocked("RISK_ARITHMETIC_VALUE_OUT_OF_RANGE")
            return blocked("INSTRUMENT_RISK_METADATA_UNAVAILABLE")
        quote = quotes_by_key.get((position.instrument, position.exchange))
        side = "BUY" if signal.target_position > 0 else "SELL"
        if risk.trading_permitted is not True or risk.route_permitted is not True:
            return blocked("INSTRUMENT_NOT_AUTHORIZED")
        if quote is None:
            return blocked("CURRENT_QUOTE_UNAVAILABLE")
        price = _quote_for_order(
            quote,
            risk,
            side=side,
            after=target.available_at,
            evaluated_at=inputs.evaluated_at,
            max_age=policy.quote_max_age_seconds,
        )
        if price is None:
            return blocked("CURRENT_QUOTE_INVALID_OR_STALE")
        if not _state_is_fresh(
            target.available_at, inputs.evaluated_at, policy.max_state_age_seconds
        ):
            return blocked("TARGET_DECISION_STALE")
        tick = quote.tick_size
        lower = quote.lower_limit
        upper = quote.upper_limit
        if tick is None or lower is None or upper is None:
            return blocked("PRICE_METADATA_UNAVAILABLE")
        margin = long_margin_upper if side == "BUY" else short_margin_upper
        risk_price_values = (quote.risk_bid_upper, quote.risk_ask_upper)
        if any(value is None for value in risk_price_values):
            return blocked("RISK_ARITHMETIC_VALUE_OUT_OF_RANGE")
        risk_notional_price = max(risk_price_values)
        risk_tick = risk.risk_tick_size_upper
        if risk_tick is None:
            risk_tick = quote.risk_tick_size_upper
        if (
            risk.risk_tick_size_upper is not None
            and quote.risk_tick_size_upper is not None
            and risk.risk_tick_size_upper != quote.risk_tick_size_upper
        ):
            return blocked("PRICE_METADATA_UNAVAILABLE")
        if risk_tick is None:
            return blocked("RISK_ARITHMETIC_VALUE_OUT_OF_RANGE")
        notional = _risk_ceiling_product(risk_notional_price, multiplier_upper)
        # Keep the stop order on the exact canonical contract grid. The risk
        # loss uses the outward tick envelope, which is a separate bound.
        stop_distance = _risk_ceiling_product(tick, policy.stop_loss_ticks)
        risk_stop_distance = _risk_ceiling_product(risk_tick, policy.stop_loss_ticks)
        stop_loss_notional = _risk_ceiling_product(
            risk_stop_distance, multiplier_upper
        )
        loss = (
            _risk_ceiling_sum(stop_loss_notional, fee_bound)
            if stop_loss_notional is not None
            else None
        )
        if (
            notional is None
            or stop_distance is None
            or risk_stop_distance is None
            or loss is None
        ):
            return blocked("RISK_ARITHMETIC_VALUE_OUT_OF_RANGE")
        stop_price = _risk_stop_price(price, stop_distance, side)
        if stop_price is None:
            return blocked("RISK_ARITHMETIC_VALUE_OUT_OF_RANGE")
        if (
            notional > policy.max_notional_per_position
            or margin > policy.max_margin_per_position
            or loss > policy.max_loss_per_position
            or stop_price < lower
            or stop_price > upper
            or not _price_is_on_tick(stop_price, tick)
        ):
            return blocked("POSITION_RISK_LIMIT")
        required_margin = _risk_ceiling_sum(required_margin, margin)
        added_notional = _risk_ceiling_sum(added_notional, notional)
        added_loss = _risk_ceiling_sum(added_loss, loss)
        if required_margin is None or added_notional is None or added_loss is None:
            return blocked("RISK_ARITHMETIC_VALUE_OUT_OF_RANGE")
        open_actions.append(
            Alpha003OrderAction(
                action="SUBMIT",
                target_id=signal.target_id,
                instrument=position.instrument,
                side=side,
                position_effect="OPEN",
                quantity=1,
                limit_price=price,
                offset="open",
                reason="ALPHA003_TARGET",
                planned_stop_price=stop_price,
                exchange=position.exchange,
                decision_available_at=inputs.evaluated_at,
                entry_grid_ordinal=inputs.eligible_grid_ordinal,
            )
        )
        open_risk_legs.append(
            Alpha003OpenRiskLegCandidate(
                target_id=signal.target_id,
                instrument=position.instrument,
                exchange=position.exchange,
                side=side,
                quantity=1,
                entry_price=price,
                stop_price=stop_price,
                multiplier=multiplier_upper,
                margin=margin,
                notional=notional,
                stop_loss=stop_loss_notional,
                round_trip_fee_upper_bound=fee_bound,
                worst_case_loss=loss,
                commission_fee_required=risk.commission_fee_required,
                commission_fee_status=risk.commission_fee_status,
                instrument_snapshot_id=risk.snapshot_id,
                quote_source_ref=quote.source_ref,
                quote_metadata_snapshot_id=quote.metadata_snapshot_id,
                quote_generation=quote.generation,
                quote_sequence=quote.sequence,
                quote_event_time=quote.event_time,
                quote_available_at=quote.available_at,
                quote_bid=quote.bid,
                quote_ask=quote.ask,
                quote_bid_size=quote.bid_size,
                quote_ask_size=quote.ask_size,
            )
        )
    total_margin = _risk_ceiling_sum(account.used_margin, required_margin)
    total_notional = _risk_ceiling_sum(account.current_notional, added_notional)
    total_worst_case_loss = _risk_ceiling_sum(
        account.current_worst_case_loss, held_fee_reserve, added_loss
    )
    if total_margin is None or total_notional is None or total_worst_case_loss is None:
        return blocked("RISK_ARITHMETIC_VALUE_OUT_OF_RANGE")
    if (
        required_margin > account.available_margin
        or total_margin > policy.max_total_margin
        or total_notional > policy.max_total_notional
        or total_worst_case_loss > policy.max_total_loss
    ):
        return blocked("ACCOUNT_RISK_LIMIT")
    if len(open_actions) > policy.max_order_intents_per_grid:
        return blocked("ORDER_INTENT_BUDGET_EXCEEDED")
    if inputs.run_order_intents_used is None:
        return blocked("RUN_ORDER_BUDGET_UNAVAILABLE")
    reserved_exit_intents = _future_exit_intent_reserve(
        inputs, proposed_open_actions=tuple(open_actions)
    )
    if (
        inputs.run_order_intents_used + len(open_actions) + reserved_exit_intents
        > policy.max_order_intents_per_run
    ):
        return blocked("RUN_ORDER_BUDGET_EXCEEDED")
    open_risk_candidate = Alpha003OpenRiskCandidate(
        schema="backtrader.alpha003.open_risk_candidate.v1",
        evidence_source=inputs.evidence_source,
        strategy_scope=inputs.strategy_scope,
        batch_id=target.batch_id,
        risk_policy_id=policy.risk_policy_id,
        account_scope=account.account_scope,
        account_snapshot_id=account.snapshot_id,
        query_set_id=inputs.dated_query_set_id,
        account_fingerprint=inputs.dated_account_fingerprint,
        connection_generation=inputs.dated_connection_generation,
        trading_day=inputs.dated_trading_day,
        source_snapshot_id=inputs.dated_snapshot_id,
        eligible_grid_ordinal=inputs.eligible_grid_ordinal,
        account_available_at=account.available_at,
        risk_evidence_available_at=inputs.risk_evidence_available_at,
        available_margin=account.available_margin,
        used_margin=account.used_margin,
        current_notional=account.current_notional,
        current_worst_case_loss=account.current_worst_case_loss,
        held_fee_reserve=held_fee_reserve,
        required_margin=required_margin,
        added_notional=added_notional,
        added_loss=added_loss,
        projected_total_margin=total_margin,
        projected_total_notional=total_notional,
        projected_total_worst_case_loss=total_worst_case_loss,
        max_total_margin=policy.max_total_margin,
        max_total_notional=policy.max_total_notional,
        max_total_loss=policy.max_total_loss,
        legs=tuple(open_risk_legs),
    )
    # This immutable planner output records the exact per-leg and aggregate
    # risk bounds. It is not a Journal reservation and grants no dispatch
    # authority; the existing fee-pair OPEN fence remains authoritative.
    return completed("READY", None, open_actions, open_risk_candidate)


def _require_text(value: Any, label: str) -> None:
    if not isinstance(value, str) or not value:
        raise ValueError("%s must be a non-empty string" % label)


def _require_utc_datetime(value: Any, label: str) -> None:
    if not isinstance(value, datetime) or value.tzinfo is None:
        raise ValueError("%s must be a timezone-aware datetime" % label)
    if value.utcoffset() != timedelta(0):
        raise ValueError("%s must be UTC" % label)


def _require_epoch(value: Any) -> None:
    if type(value) is not int or value < 1:
        raise ValueError("epoch_id must be a positive integer")


def _normalize_product_key(value: Any, label: str) -> ProductKey:
    if not isinstance(value, (tuple, list)) or len(value) != 2:
        raise ValueError("%s must be a non-empty (exchange, product_id) pair" % label)
    key = tuple(value)
    if any(not isinstance(part, str) or not part for part in key):
        raise ValueError("%s must be a non-empty (exchange, product_id) pair" % label)
    return key


def _read(source: Any, name: str) -> Any:
    if isinstance(source, Mapping):
        try:
            return source[name]
        except KeyError:
            raise AttributeError("shared source is missing required field %s" % name) from None
    try:
        return getattr(source, name)
    except AttributeError:
        raise AttributeError("shared source is missing required field %s" % name) from None


def _state_name(value: Any, label: str) -> str:
    enum_value = getattr(value, "value", None)
    if isinstance(enum_value, str) and enum_value:
        return str(enum_value)
    if isinstance(value, str) and value:
        return str(value)
    raise TypeError("%s must be a string or string-valued enum" % label)


def make_alpha003_factor_spec(
    *, mode: str = DEFAULT_FACTOR_MODE, direction: int = DEFAULT_DIRECTION
) -> FactorSpec:
    """Declare the production Alpha003 class with its explicit streamed fields."""

    return FactorSpec(
        FACTOR_NAME,
        get_alpha(3),
        FACTOR_PANEL_LINE,
        field_bindings={
            "open": "feed:target:open",
            "volume": "feed:target:volume",
        },
        direction=direction,
        mode=mode,
    )


def make_alpha003_live_plan(
    targets: Iterable[str],
    *,
    calendar_id: str,
    mode: str = DEFAULT_FACTOR_MODE,
    direction: int = DEFAULT_DIRECTION,
    preheat_bars: int = DEFAULT_PREHEAT_BARS,
    max_pending_slots: int = 8,
    max_window_bars: int = 512,
    wait_timeout_ns: int = 5_000_000_000,
    max_live_bar_age_seconds: float = 60.0,
    max_future_skew_seconds: float = 0.0,
) -> Any:
    """Build the shared one-factor, one-minute plan; no scheduler is implemented here."""

    from backtrader.research.live import LiveFactorPlan

    spec = make_alpha003_factor_spec(mode=mode, direction=direction)
    return LiveFactorPlan(
        targets=tuple(targets),
        factors={spec.name: spec},
        calendar_id=calendar_id,
        frequency=FACTOR_FREQUENCY,
        warmup_min_bars=preheat_bars,
        max_pending_slots=max_pending_slots,
        max_window_bars=max_window_bars,
        wait_timeout_ns=wait_timeout_ns,
        max_live_bar_age_seconds=max_live_bar_age_seconds,
        max_future_skew_seconds=max_future_skew_seconds,
    )


def policy_input_from_shared_snapshot(
    cohort_batch: Any,
    factor_snapshot: Any,
    *,
    required_targets: Iterable[str],
    authorized_targets: Iterable[str],
    product_keys: Mapping[str, ProductKey],
    factor_name: str = FACTOR_NAME,
    execution_mode: str = "LIVE",
    eligible_grid_index: int = 0,
    rebalance_every: int = DEFAULT_REBALANCE_GRIDS,
) -> Alpha003PolicyInput:
    """Project the shared immutable APIs into the small pure policy contract."""

    cohort_facts = CohortBatchFacts(
        status=_state_name(_read(cohort_batch, "status"), "cohort status"),
        batch_id=_read(cohort_batch, "batch_id"),
        cohort_id=_read(cohort_batch, "cohort_id"),
        calendar_id=_read(cohort_batch, "calendar_id"),
        epoch_id=_read(cohort_batch, "epoch_id"),
        close_time=_read(cohort_batch, "close_time"),
        available_at=_read(cohort_batch, "available_at"),
    )
    factor_blocks = _read(factor_snapshot, "factors")
    if not isinstance(factor_blocks, Mapping) or factor_name not in factor_blocks:
        raise ValueError("shared snapshot does not contain factor %s" % factor_name)
    factor_block = factor_blocks[factor_name]
    raw_values = _read(factor_block, "values")
    if not isinstance(raw_values, Mapping):
        raise TypeError("shared factor values must be an immutable target mapping")

    required = tuple(required_targets)
    points = []
    for target in required:
        row = raw_values.get(target)
        if row is None:
            points.append(
                FactorPoint(
                    target,
                    product_keys.get(target),
                    None,
                    "OUTPUT_UNAVAILABLE",
                    False,
                    False,
                    "MISSING",
                )
            )
            continue
        points.append(
            FactorPoint(
                target_id=target,
                product_key=product_keys.get(target),
                value=_read(row, "value"),
                status=_state_name(_read(row, "status"), "factor output status"),
                present=_read(row, "present"),
                complete=_read(row, "complete"),
                quality=_state_name(_read(row, "quality"), "factor output quality"),
                source_role=_state_name(_read(row, "source_role"), "factor source role"),
                source_ref=(
                    _read(row, "source_ref") if isinstance(_read(row, "source_ref"), str) else None
                ),
                generation=_read(row, "generation"),
            )
        )
    extras = set(raw_values) - set(required)
    for target in sorted(extras, key=repr):
        if not isinstance(target, str) or not target:
            raise TypeError("shared factor target keys must be non-empty strings")
        row = raw_values[target]
        points.append(
            FactorPoint(
                target_id=target,
                product_key=product_keys.get(target),
                value=_read(row, "value"),
                status=_state_name(_read(row, "status"), "factor output status"),
                present=_read(row, "present"),
                complete=_read(row, "complete"),
                quality=_state_name(_read(row, "quality"), "factor output quality"),
                source_role=_state_name(_read(row, "source_role"), "factor source role"),
                source_ref=(
                    _read(row, "source_ref") if isinstance(_read(row, "source_ref"), str) else None
                ),
                generation=_read(row, "generation"),
            )
        )

    mode = execution_mode.upper() if isinstance(execution_mode, str) else execution_mode
    readiness = _state_name(_read(factor_snapshot, "readiness"), "factor readiness")
    if mode == "REPLAY":
        # History batches intentionally stay WARMUP in LiveFactorSet. Replay
        # may derive its own calculation-ready state only from the same exact
        # complete receipt and available history outputs.
        replay_rows_ready = all(
            point.source_role is not None
            and point.source_role.lower() == "history"
            and point.status == "OUTPUT_AVAILABLE"
            and point.present
            and point.complete
            and point.quality == "GOOD"
            and point.value is not None
            and math.isfinite(point.value)
            for point in points
        )
        replay_receipt_ready = (
            cohort_facts.status == "COMPLETE"
            and _read(factor_snapshot, "batch_complete") is True
            and _read(factor_snapshot, "batch_id") == cohort_facts.batch_id
            and _read(factor_snapshot, "cohort_id") == cohort_facts.cohort_id
            and _read(factor_snapshot, "calendar_id") == cohort_facts.calendar_id
            and _read(factor_snapshot, "epoch_id") == cohort_facts.epoch_id
            and _read(factor_snapshot, "close_time") == cohort_facts.close_time
            and _read(factor_snapshot, "available_at") == cohort_facts.available_at
            and cohort_facts.available_at >= cohort_facts.close_time
        )
        readiness = (
            "REPLAY_READY" if replay_rows_ready and replay_receipt_ready else "REPLAY_WARMUP"
        )
    elif mode != "LIVE":
        raise ValueError("execution_mode must be LIVE or REPLAY")

    factor_facts = FactorSnapshotFacts(
        readiness=readiness,
        batch_complete=_read(factor_snapshot, "batch_complete"),
        batch_id=_read(factor_snapshot, "batch_id"),
        cohort_id=_read(factor_snapshot, "cohort_id"),
        calendar_id=_read(factor_snapshot, "calendar_id"),
        epoch_id=_read(factor_snapshot, "epoch_id"),
        close_time=_read(factor_snapshot, "close_time"),
        available_at=_read(factor_snapshot, "available_at"),
        factor_name=factor_name,
        mode=_state_name(_read(factor_block, "mode"), "factor mode"),
        direction=_read(factor_block, "direction"),
        source_sha256=_read(factor_block, "source_sha256"),
        points=tuple(points),
    )
    return Alpha003PolicyInput(
        cohort=cohort_facts,
        factor=factor_facts,
        required_targets=required,
        authorized_targets=frozenset(authorized_targets),
        eligible_grid_index=eligible_grid_index,
        rebalance_every=rebalance_every,
        execution_mode=mode,
    )


def select_alpha003_targets(policy_input: Alpha003PolicyInput) -> Alpha003TargetDecision:
    """Select one long and one short signal target without making order decisions."""

    if not isinstance(policy_input, Alpha003PolicyInput):
        raise TypeError("policy_input must be Alpha003PolicyInput")
    cohort = policy_input.cohort
    factor = policy_input.factor
    base = {
        "factor_name": factor.factor_name,
        "mode": factor.mode,
        "execution_mode": policy_input.execution_mode,
        "direction": factor.direction,
        "source_sha256": factor.source_sha256,
        "cohort_id": cohort.cohort_id,
        "batch_id": cohort.batch_id,
        "close_time": factor.close_time,
        "available_at": factor.available_at,
        "eligible_grid_index": policy_input.eligible_grid_index,
        "rebalance_every": policy_input.rebalance_every,
        "authorized_targets": tuple(sorted(policy_input.authorized_targets)),
        "eligible_targets": (),
        "targets": (),
    }

    def blocked(reason: str, eligible: Tuple[str, ...] = ()) -> Alpha003TargetDecision:
        return Alpha003TargetDecision(
            status="BLOCKED",
            reason=reason,
            eligible_targets=eligible,
            **{key: value for key, value in base.items() if key != "eligible_targets"},
        )

    gate_reason = _preselection_block_reason(policy_input)
    if gate_reason is not None:
        return blocked(gate_reason)
    if policy_input.eligible_grid_index == 0:
        return blocked("ELIGIBLE_GRID_NOT_COUNTED")
    if policy_input.eligible_grid_index % policy_input.rebalance_every:
        return blocked("REBALANCE_NOT_DUE")

    eligible = []
    for point in factor.points:
        if point.target_id not in policy_input.authorized_targets:
            continue
        if point.status != "OUTPUT_AVAILABLE" or point.value is None:
            continue
        if not math.isfinite(point.value):
            continue
        if point.product_key is None:
            return blocked("PRODUCT_KEY_UNAVAILABLE")
        eligible.append((point, point.value * factor.direction))

    ordered_ids = tuple(
        point.target_id
        for point, _score in sorted(
            eligible, key=lambda item: (item[0].product_key, item[0].target_id)
        )
    )
    if len(eligible) < 2:
        return blocked("NO_VALID_SIGNAL", ordered_ids)
    high_score = max(score for _point, score in eligible)
    low_score = min(score for _point, score in eligible)
    if high_score <= low_score:
        return blocked("NO_VALID_SIGNAL", ordered_ids)
    high = min(
        (point for point, score in eligible if score == high_score),
        key=lambda point: (point.product_key, point.target_id),
    )
    low = min(
        (point for point, score in eligible if score == low_score),
        key=lambda point: (point.product_key, point.target_id),
    )
    targets = (
        Alpha003SignalTarget(
            target_id=high.target_id,
            product_key=high.product_key,
            target_position=1,
            raw_score=high.value,
            oriented_score=high_score,
        ),
        Alpha003SignalTarget(
            target_id=low.target_id,
            product_key=low.product_key,
            target_position=-1,
            raw_score=low.value,
            oriented_score=low_score,
        ),
    )
    return Alpha003TargetDecision(
        status="TARGETS_READY",
        reason=None,
        eligible_targets=ordered_ids,
        targets=targets,
        **{key: value for key, value in base.items() if key not in ("eligible_targets", "targets")},
    )


def _preselection_block_reason(policy_input: Alpha003PolicyInput) -> Optional[str]:
    """Return a gate reason before grid counting or target selection."""

    cohort = policy_input.cohort
    factor = policy_input.factor
    if cohort.status != "COMPLETE":
        return "COHORT_NOT_COMPLETE"
    if not factor.batch_complete:
        return "FACTOR_BATCH_NOT_COMPLETE"
    expected_readiness = "LIVE_READY" if policy_input.execution_mode == "LIVE" else "REPLAY_READY"
    if factor.readiness != expected_readiness:
        return (
            "FACTOR_NOT_LIVE_READY"
            if policy_input.execution_mode == "LIVE"
            else "FACTOR_NOT_REPLAY_READY"
        )
    identity_pairs = (
        (cohort.batch_id, factor.batch_id),
        (cohort.cohort_id, factor.cohort_id),
        (cohort.calendar_id, factor.calendar_id),
        (cohort.epoch_id, factor.epoch_id),
        (cohort.close_time, factor.close_time),
        (cohort.available_at, factor.available_at),
    )
    if any(left != right for left, right in identity_pairs):
        return "COHORT_SNAPSHOT_MISMATCH"
    if cohort.available_at < cohort.close_time or factor.available_at < factor.close_time:
        return "INVALID_AVAILABILITY_ORDER"
    if not policy_input.required_targets:
        return "EMPTY_FACTOR_POOL"
    if not policy_input.authorized_targets.issubset(set(policy_input.required_targets)):
        return "INVALID_AUTHORIZED_SUBSET"
    point_ids = tuple(point.target_id for point in factor.points)
    if len(set(point_ids)) != len(point_ids) or set(point_ids) != set(
        policy_input.required_targets
    ):
        return "FACTOR_TARGET_SET_MISMATCH"
    if any(not point.present or not point.complete for point in factor.points):
        return "INPUT_INCOMPLETE"
    if any(point.quality != "GOOD" for point in factor.points):
        return "INPUT_QUALITY_UNAVAILABLE"
    return None


def _product_key_mapping(value: Any, targets: Tuple[str, ...]) -> Mapping[str, ProductKey]:
    if value is None:
        value = {}
    if not isinstance(value, Mapping):
        raise TypeError("product_keys must map each target feed name to (exchange, product_id)")
    if set(value) - set(targets):
        raise ValueError("product_keys may only name declared target feeds")
    normalized = {}
    for target in targets:
        key = value.get(target)
        if key is None:
            continue
        normalized[target] = _normalize_product_key(key, "product_keys[%r]" % target)
    return normalized


def _risk_policy(value: Any) -> Optional[Alpha003RiskPolicy]:
    if value is None or isinstance(value, Alpha003RiskPolicy):
        return value
    if not isinstance(value, Mapping):
        raise TypeError("risk_policy must be Alpha003RiskPolicy, a complete mapping, or None")
    fields = tuple(Alpha003RiskPolicy.__dataclass_fields__)
    if set(value) != set(fields):
        raise ValueError("risk_policy mapping must provide every explicit policy field")
    normalized = dict(value)
    decimal_fields = (
        "quote_max_age_seconds",
        "max_state_age_seconds",
        "max_notional_per_position",
        "max_total_notional",
        "max_margin_per_position",
        "max_total_margin",
        "max_loss_per_position",
        "max_total_loss",
    )
    for name in decimal_fields:
        normalized[name] = _positive_decimal(normalized[name], name)
    if normalized["round_trip_fee_upper_bound_per_contract"] is not None:
        normalized["round_trip_fee_upper_bound_per_contract"] = _nonnegative_decimal(
            normalized["round_trip_fee_upper_bound_per_contract"],
            "round_trip_fee_upper_bound_per_contract",
        )
    return Alpha003RiskPolicy(**normalized)


def _replay_exact_text(value: Any) -> Optional[str]:
    """Return canonical non-empty replay metadata without coercion or truth tests."""

    if type(value) is not str or not value or value != value.strip():
        return None
    return value


def _replay_owner_intent_id(info: Mapping[str, Any]) -> Optional[str]:
    """Read one exact owner field; malformed primary metadata never falls back."""

    try:
        owner_id = info.get("replay_owner_intent_id")
        if owner_id is None:
            owner_id = info.get("factor_intent_id")
    except Exception:
        return None
    return _replay_exact_text(owner_id)


def _exact_hands(value: Any) -> Optional[int]:
    if value is None or isinstance(value, bool):
        return None
    try:
        number = value if isinstance(value, Decimal) else Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return None
    if not number.is_finite() or number != number.to_integral_value():
        return None
    return int(number)


def _as_utc(value: Any, label: str) -> datetime:
    _require_utc_datetime(value, label)
    return value.astimezone(timezone.utc)


def _time_key(value: datetime) -> str:
    return _as_utc(value, "decision close_time").isoformat().replace("+00:00", "Z")


def _canonical_source_trading_day(value: Any) -> str:
    """Return the decision tape's ISO day form without accepting loose dates."""

    if type(value) is not str:
        raise ValueError("source receipt trading_day is invalid")
    if len(value) == 8 and value.isascii() and value.isdecimal():
        try:
            parsed = datetime.strptime(value, "%Y%m%d").date()
        except ValueError:
            raise ValueError("source receipt trading_day is invalid") from None
        return parsed.isoformat()
    if (
        len(value) == 10
        and value[4] == "-"
        and value[7] == "-"
        and value[:4].isascii()
        and value[:4].isdecimal()
        and value[5:7].isascii()
        and value[5:7].isdecimal()
        and value[8:].isascii()
        and value[8:].isdecimal()
    ):
        try:
            parsed = date.fromisoformat(value)
        except ValueError:
            raise ValueError("source receipt trading_day is invalid") from None
        if parsed.isoformat() == value:
            return value
    raise ValueError("source receipt trading_day is invalid")


def _decimal_or_none(value: Any) -> Optional[Decimal]:
    if value is None:
        return None
    try:
        return _decimal_number(value, "execution fact")
    except ValueError:
        return None


def _replay_quote(value: Any) -> Alpha003ReplayQuoteFact:
    if isinstance(value, Alpha003ReplayQuoteFact):
        return value
    if not isinstance(value, Mapping):
        raise TypeError("replay_quotes must contain typed quote facts or immutable mappings")
    return Alpha003ReplayQuoteFact(
        instrument=value.get("instrument"),
        exchange=value.get("exchange"),
        event_time=value.get("event_time"),
        available_at=value.get("available_at"),
        bid=value.get("bid"),
        ask=value.get("ask"),
        source_ref=value.get("source_ref"),
        quote_id=value.get("quote_id"),
    )


def _session_close_from_batch(
    batch: Any,
    *,
    data_by_target: Mapping[str, Any],
    product_keys: Mapping[str, ProductKey],
    routes: Mapping[str, Tuple[str, str]],
    session_calendars: Mapping[str, Any],
) -> Tuple[Optional[datetime], Optional[str]]:
    """Resolve one common session end from the sealed source calendar and receipts."""

    if batch is None:
        return None, "COHORT_BATCH_UNAVAILABLE"
    try:
        from backtrader.feeds.futures_main_contract import ProductKey as FrozenProductKey
        from backtrader.feeds.futures_sessions import ExchangeSessionCalendar
    except ImportError:
        return None, "SESSION_CALENDAR_API_UNAVAILABLE"

    ends = []
    members = _read(batch, "members")
    if not isinstance(members, Mapping) or not members:
        return None, "COHORT_MEMBER_RECEIPTS_UNAVAILABLE"
    for target_id, data in data_by_target.items():
        receipt_getter = getattr(batch, "receipt_for_feed", None)
        receipt = receipt_getter(data) if callable(receipt_getter) else None
        if receipt is None:
            return None, "TARGET_RECEIPT_UNAVAILABLE"
        envelope = _read(receipt, "envelope")
        raw_day = _read(envelope, "trading_day")
        if isinstance(raw_day, date) and not isinstance(raw_day, datetime):
            trading_day = raw_day
        elif isinstance(raw_day, str):
            try:
                trading_day = date.fromisoformat(raw_day.replace("-", ""))
            except ValueError:
                try:
                    trading_day = date.fromisoformat(raw_day)
                except ValueError:
                    return None, "TRADING_DAY_INVALID"
        else:
            return None, "TRADING_DAY_UNAVAILABLE"
        segment = _read(envelope, "session_segment")
        if not isinstance(segment, str) or not segment:
            return None, "SESSION_SEGMENT_UNAVAILABLE"
        product = product_keys.get(target_id)
        route = routes.get(target_id)
        if product is None or route is None:
            return None, "PRODUCT_ROUTE_UNAVAILABLE"
        instrument, exchange = route
        del instrument
        calendar = session_calendars.get(exchange)
        if type(calendar) is not ExchangeSessionCalendar or calendar.complete is not True:
            return None, "SESSION_CALENDAR_UNAVAILABLE"
        frozen_product = FrozenProductKey(product[0], product[1])
        if frozen_product.exchange_id != calendar.exchange_id:
            return None, "SESSION_CALENDAR_EXCHANGE_MISMATCH"
        rows = [
            row
            for row in calendar.product_days
            if row.product == frozen_product and row.trading_day == trading_day
        ]
        if len(rows) != 1:
            return None, "PRODUCT_SESSION_ROW_UNAVAILABLE"
        windows = [window for window in rows[0].windows if window.session_id == segment]
        if len(windows) != 1:
            return None, "SESSION_WINDOW_UNAVAILABLE"
        ends.append(windows[0].end.astimezone(timezone.utc))
    if not ends or any(value != ends[0] for value in ends[1:]):
        return None, "COMMON_SESSION_END_MISMATCH"
    return ends[0], None


def _live_planning_input(
    facts: Any,
    *,
    strategy_scope: str,
    evaluated_at: datetime,
    risk_evidence_available_at: Optional[datetime],
    session_close_at: Optional[datetime],
    run_end: bool,
    risk_policy: Optional[Alpha003RiskPolicy],
    target_decision: Optional[Alpha003TargetDecision],
    eligible_grid_ordinal: Optional[int],
    run_order_intents_used: Optional[int],
) -> Alpha003OrderPlanningInput:
    """Thinly map the shared no-I/O RegisteredSim facts projection."""

    positions = []
    mapper_blockers = []
    for item in facts.positions:
        quantity = _exact_hands(item.quantity)
        if item.quantity is not None and quantity is None:
            mapper_blockers.append("FRACTIONAL_POSITION_QUANTITY")
        positions.append(
            Alpha003PositionFact(
                target_id=item.target_id,
                instrument=item.instrument,
                exchange=item.exchange,
                quantity=quantity,
                snapshot_id=item.snapshot_id,
                available_at=item.available_at,
                owner_strategy_scope=item.owner_strategy_scope,
                owner_intent_id=item.owner_intent_id,
                average_price=item.average_price,
                stop_price=item.stop_price,
                held_eligible_bars=item.held_eligible_bars,
                risk_average_price_lower=getattr(item, "risk_average_price_lower", None),
                risk_average_price_upper=getattr(item, "risk_average_price_upper", None),
                risk_stop_price_lower=getattr(item, "risk_stop_price_lower", None),
                risk_stop_price_upper=getattr(item, "risk_stop_price_upper", None),
            )
        )
    orders = []
    for item in facts.working_orders:
        remaining = _exact_hands(item.remaining_quantity)
        if item.remaining_quantity is not None and remaining is None:
            mapper_blockers.append("FRACTIONAL_WORKING_QUANTITY")
        state = item.state
        if item.execution_unknown is True:
            state = "UNKNOWN"
        elif item.cancel_pending is True:
            state = "CANCEL_PENDING"
        orders.append(
            Alpha003WorkingOrderFact(
                target_id=item.target_id,
                instrument=item.instrument,
                exchange=item.exchange,
                order_ref=item.order_ref,
                broker_order_ref=item.broker_order_ref,
                state=str(state).upper(),
                side=item.side,
                position_effect=item.position_effect,
                remaining_quantity=remaining,
                owner_strategy_scope=item.owner_strategy_scope,
                owner_intent_id=item.owner_intent_id,
            )
        )
    quotes = [
        Alpha003QuoteFact(
            instrument=item.instrument,
            exchange=item.exchange,
            source_ref=item.source_ref,
            metadata_snapshot_id=item.metadata_snapshot_id,
            generation=item.generation,
            sequence=item.sequence,
            event_time=item.event_time,
            available_at=item.available_at,
            bid=item.bid,
            ask=item.ask,
            bid_size=item.bid_size,
            ask_size=item.ask_size,
            tick_size=item.tick_size,
            lower_limit=item.lower_limit,
            upper_limit=item.upper_limit,
            quality=item.quality,
            evidence_source="REGISTERED_SIM",
            risk_bid_lower=getattr(item, "risk_bid_lower", None),
            risk_bid_upper=getattr(item, "risk_bid_upper", None),
            risk_ask_lower=getattr(item, "risk_ask_lower", None),
            risk_ask_upper=getattr(item, "risk_ask_upper", None),
            risk_bid_size_lower=getattr(item, "risk_bid_size_lower", None),
            risk_ask_size_lower=getattr(item, "risk_ask_size_lower", None),
            risk_tick_size_upper=getattr(item, "risk_tick_size_upper", None),
        )
        for item in facts.quotes
    ]
    route_by_target = {item.target_id: item for item in facts.route_eligibilities}
    instruments = []
    for item in facts.instruments:
        route = route_by_target.get(item.target_id)
        if route is None or (route.instrument, route.exchange) != (item.instrument, item.exchange):
            mapper_blockers.append("ROUTE_IDENTITY_UNAVAILABLE")
            route_permitted = None
        else:
            route_permitted = route.eligible
        instruments.append(
            Alpha003InstrumentRiskFact(
                target_id=item.target_id,
                instrument=item.instrument,
                exchange=item.exchange,
                snapshot_id=item.snapshot_id,
                available_at=item.available_at,
                trading_permitted=item.trading_permitted,
                multiplier=item.multiplier,
                long_margin_per_hand=item.long_margin_per_hand,
                short_margin_per_hand=item.short_margin_per_hand,
                tick_size=item.tick_size,
                lower_limit=item.lower_limit,
                upper_limit=item.upper_limit,
                route_permitted=route_permitted,
                risk_multiplier_upper=getattr(item, "risk_multiplier_upper", None),
                risk_long_margin_per_hand_upper=(
                    getattr(item, "risk_long_margin_per_hand_upper", None)
                ),
                risk_short_margin_per_hand_upper=(
                    getattr(item, "risk_short_margin_per_hand_upper", None)
                ),
                risk_tick_size_upper=getattr(item, "risk_tick_size_upper", None),
                round_trip_fee_upper_bound_per_contract=(
                    item.round_trip_fee_upper_bound_per_contract
                ),
                commission_fee_required=getattr(item, "commission_fee_required", False),
                commission_fee_status=getattr(item, "commission_fee_status", "NOT_REQUIRED"),
            )
        )
    account_fact = facts.account
    account = None
    if account_fact is not None and account_fact.snapshot_id is not None:
        account = Alpha003AccountRiskFact(
            account_scope=account_fact.account_scope,
            snapshot_id=account_fact.snapshot_id,
            available_at=account_fact.available_at,
            route_permitted=account_fact.route_permitted,
            available_margin=account_fact.available_margin,
            used_margin=account_fact.used_margin,
            current_notional=account_fact.current_notional,
            current_worst_case_loss=account_fact.current_worst_case_loss,
        )
    aggregate_blockers = tuple(getattr(facts, "open_risk_blockers", tuple(facts.blockers)))
    blockers = tuple(dict.fromkeys(aggregate_blockers + tuple(mapper_blockers)))
    return Alpha003OrderPlanningInput(
        strategy_scope=strategy_scope,
        evaluated_at=evaluated_at,
        risk_evidence_available_at=risk_evidence_available_at or facts.available_at,
        session_close_at=session_close_at,
        run_end=run_end,
        risk_policy=risk_policy,
        account=account,
        positions=tuple(positions),
        working_orders=tuple(orders),
        quotes=tuple(quotes),
        instruments=tuple(instruments),
        target_decision=target_decision,
        run_order_intents_used=run_order_intents_used,
        execution_blockers=blockers,
        eligible_grid_ordinal=eligible_grid_ordinal,
        risk_reduction_ready=facts.risk_reduction_ready,
        risk_reduction_blockers=tuple(facts.risk_reduction_blockers),
        open_risk_ready=facts.open_risk_ready,
        open_risk_blockers=aggregate_blockers,
        order_cancel_ready=getattr(facts, "order_cancel_ready", False) is True,
        order_cancel_blockers=tuple(getattr(facts, "order_cancel_blockers", ())),
        evidence_source="REGISTERED_SIM",
        dated_close_legs=tuple(getattr(facts, "dated_close_legs", ())),
        dated_query_set_id=getattr(facts, "query_set_id", None),
        dated_snapshot_id=getattr(facts, "snapshot_id", None),
        dated_account_fingerprint=(
            getattr(account_fact, "account_fingerprint", None) if account_fact is not None else None
        ),
        dated_connection_generation=(
            getattr(account_fact, "connection_generation", None)
            if account_fact is not None
            else None
        ),
        dated_trading_day=(
            getattr(account_fact, "trading_day", None) if account_fact is not None else None
        ),
        dated_available_at=getattr(facts, "available_at", None),
        execution_target_ids=(
            tuple(facts.execution_target_ids)
            if isinstance(getattr(facts, "execution_target_ids", None), tuple)
            else None
        ),
    )


def _live_execution_evidence_payload(facts: Any) -> Mapping[str, Any]:
    """Bind the source clocks and identities used by a durable order decision."""

    if facts is None:
        return MappingProxyType({})

    quotes = []
    for quote in getattr(facts, "quotes", ()):
        quotes.append(
            {
                "instrument": quote.instrument,
                "exchange": quote.exchange,
                "source_ref": quote.source_ref,
                "metadata_snapshot_id": quote.metadata_snapshot_id,
                "generation": quote.generation,
                "sequence": quote.sequence,
                "event_time": _time_key(quote.event_time) if quote.event_time else None,
                "available_at": _time_key(quote.available_at) if quote.available_at else None,
                "quality": quote.quality,
                "bid": str(quote.bid) if quote.bid is not None else None,
                "ask": str(quote.ask) if quote.ask is not None else None,
            }
        )
    queries = []
    for query in getattr(facts, "query_provenance", ()):
        queries.append(
            {
                "family": query.family,
                "target_id": query.target_id,
                "request_id": query.request_id,
                "connection_generation": query.connection_generation,
                "started_at": _time_key(query.started_at) if query.started_at else None,
                "completed_at": _time_key(query.completed_at) if query.completed_at else None,
                "query_complete": query.query_complete,
                "scope_complete": query.scope_complete,
                "row_count": query.row_count,
            }
        )
    account = getattr(facts, "account", None)
    return MappingProxyType(
        {
            "snapshot_id": facts.snapshot_id,
            "available_at": _time_key(facts.available_at) if facts.available_at else None,
            "account_snapshot_id": getattr(account, "snapshot_id", None),
            "account_available_at": (
                _time_key(account.available_at)
                if account is not None and account.available_at is not None
                else None
            ),
            "quotes": tuple(quotes),
            "query_provenance": tuple(queries),
        }
    )


def _planned_action_payload(action: Alpha003OrderAction) -> Mapping[str, Any]:
    """Serialize a shadow/order-plan preview without declaring an intent."""

    return MappingProxyType(
        {
            "action": action.action,
            "target_id": action.target_id,
            "instrument": action.instrument,
            "exchange": action.exchange,
            "side": action.side,
            "position_effect": action.position_effect,
            "quantity": action.quantity,
            "limit_price": str(action.limit_price) if action.limit_price is not None else None,
            "offset": action.offset,
            "reason": action.reason,
            "order_ref": action.order_ref,
            "owner_intent_id": action.owner_intent_id,
            "planned_stop_price": (
                str(action.planned_stop_price) if action.planned_stop_price is not None else None
            ),
            "entry_grid_ordinal": action.entry_grid_ordinal,
            "broker_order_ref": action.broker_order_ref,
            "position_side": action.position_side,
            "dated_position_side": action.dated_position_side,
            "position_date": action.position_date,
            "offset_flag": action.offset_flag,
            "hedge_flag": action.hedge_flag,
            "dated_query_set_id": action.dated_query_set_id,
            "dated_snapshot_id": action.dated_snapshot_id,
            "dated_account_fingerprint": action.dated_account_fingerprint,
            "dated_connection_generation": action.dated_connection_generation,
            "dated_trading_day": action.dated_trading_day,
            "dated_available_at": (
                _time_key(action.dated_available_at)
                if action.dated_available_at is not None
                else None
            ),
            "dated_source_row_ids": action.dated_source_row_ids,
            "dated_opening_execution_ids": action.dated_opening_execution_ids,
            "decision_available_at": (
                _time_key(action.decision_available_at)
                if action.decision_available_at is not None
                else None
            ),
        }
    )


def _open_risk_leg_candidate_payload(
    candidate: Alpha003OpenRiskLegCandidate,
) -> Mapping[str, Any]:
    """Serialize planner risk and quote identity without granting OPEN authority."""

    return MappingProxyType(
        {
            "target_id": candidate.target_id,
            "instrument": candidate.instrument,
            "exchange": candidate.exchange,
            "side": candidate.side,
            "quantity": candidate.quantity,
            "entry_price": str(candidate.entry_price),
            "stop_price": str(candidate.stop_price),
            "multiplier": str(candidate.multiplier),
            "margin": str(candidate.margin),
            "notional": str(candidate.notional),
            "stop_loss": str(candidate.stop_loss),
            "round_trip_fee_upper_bound": str(candidate.round_trip_fee_upper_bound),
            "worst_case_loss": str(candidate.worst_case_loss),
            "commission_fee_required": candidate.commission_fee_required,
            "commission_fee_status": candidate.commission_fee_status,
            "instrument_snapshot_id": candidate.instrument_snapshot_id,
            "quote_source_ref": candidate.quote_source_ref,
            "quote_metadata_snapshot_id": candidate.quote_metadata_snapshot_id,
            "quote_generation": candidate.quote_generation,
            "quote_sequence": candidate.quote_sequence,
            "quote_event_time": _time_key(candidate.quote_event_time),
            "quote_available_at": _time_key(candidate.quote_available_at),
            "quote_bid": str(candidate.quote_bid),
            "quote_ask": str(candidate.quote_ask),
            "quote_bid_size": (
                str(candidate.quote_bid_size) if candidate.quote_bid_size is not None else None
            ),
            "quote_ask_size": (
                str(candidate.quote_ask_size) if candidate.quote_ask_size is not None else None
            ),
        }
    )


def _open_risk_candidate_payload(
    candidate: Optional[Alpha003OpenRiskCandidate],
) -> Optional[Mapping[str, Any]]:
    """Keep the complete immutable planner projection on its grid decision."""

    if candidate is None:
        return None
    return MappingProxyType(
        {
            "schema": candidate.schema,
            "evidence_source": candidate.evidence_source,
            "strategy_scope": candidate.strategy_scope,
            "batch_id": candidate.batch_id,
            "risk_policy_id": candidate.risk_policy_id,
            "account_scope": candidate.account_scope,
            "account_snapshot_id": candidate.account_snapshot_id,
            "query_set_id": candidate.query_set_id,
            "account_fingerprint": candidate.account_fingerprint,
            "connection_generation": candidate.connection_generation,
            "trading_day": candidate.trading_day,
            "source_snapshot_id": candidate.source_snapshot_id,
            "eligible_grid_ordinal": candidate.eligible_grid_ordinal,
            "account_available_at": _time_key(candidate.account_available_at),
            "risk_evidence_available_at": _time_key(candidate.risk_evidence_available_at),
            "available_margin": str(candidate.available_margin),
            "used_margin": str(candidate.used_margin),
            "current_notional": str(candidate.current_notional),
            "current_worst_case_loss": str(candidate.current_worst_case_loss),
            "held_fee_reserve": str(candidate.held_fee_reserve),
            "required_margin": str(candidate.required_margin),
            "added_notional": str(candidate.added_notional),
            "added_loss": str(candidate.added_loss),
            "projected_total_margin": str(candidate.projected_total_margin),
            "projected_total_notional": str(candidate.projected_total_notional),
            "projected_total_worst_case_loss": str(
                candidate.projected_total_worst_case_loss
            ),
            "max_total_margin": str(candidate.max_total_margin),
            "max_total_notional": str(candidate.max_total_notional),
            "max_total_loss": str(candidate.max_total_loss),
            "legs": tuple(_open_risk_leg_candidate_payload(item) for item in candidate.legs),
        }
    )


class Alpha003TargetStrategy(bt.Strategy):
    """Ordinary Strategy for the shared Alpha003 factor and order policy.

    Replay uses only CausalReplayBroker plus explicit saved quote/metadata
    records. Live execution uses only the shared coordinator on BtApiBroker;
    the Strategy never calls an adapter, journal, or provider write API.
    """

    params = (
        ("cohort", None),
        ("calendar_id", None),
        ("factor_mode", DEFAULT_FACTOR_MODE),
        ("direction", DEFAULT_DIRECTION),
        ("authorized_targets", ()),
        ("product_keys", None),
        ("preheat_bars", DEFAULT_PREHEAT_BARS),
        ("max_pending_slots", 8),
        ("max_window_bars", 512),
        ("wait_timeout_ns", 5_000_000_000),
        ("rebalance_every", DEFAULT_REBALANCE_GRIDS),
        ("replay_mode", False),
        ("execution_enabled", False),
        ("risk_policy", None),
        ("replay_quotes", ()),
        ("replay_instruments", None),
        ("routes", None),
        ("session_calendars", None),
        ("account_scope", None),
        ("strategy_scope", None),
        ("logical_run_id", None),
        ("quote_max_age_seconds", None),
        ("max_query_age_seconds", None),
        ("loss_guard_net_loss_threshold", None),
        ("loss_guard_max_observation_age_seconds", None),
        ("max_live_bar_age_seconds", None),
        ("max_future_skew_seconds", None),
        ("control_refresh_loop", None),
        ("live_ready_callback", None),
        ("live_next_callback", None),
        ("live_capacity_callback", None),
        ("decision_tape", None),
        ("source_restart_marker", None),
        ("source_kind", None),
    )

    def __init__(self) -> None:
        if self.p.live_ready_callback is not None and not callable(self.p.live_ready_callback):
            raise TypeError("live_ready_callback must be callable or None")
        if self.p.live_next_callback is not None and not callable(self.p.live_next_callback):
            raise TypeError("live_next_callback must be callable or None")
        if self.p.live_capacity_callback is not None and not callable(
            self.p.live_capacity_callback
        ):
            raise TypeError("live_capacity_callback must be callable or None")
        target_ids = tuple(getattr(data, "_name", "") for data in self.datas)
        if not target_ids or any(not isinstance(name, str) or not name for name in target_ids):
            raise ValueError("each Alpha003 target feed needs an explicit non-empty name")
        if len(set(target_ids)) != len(target_ids):
            raise ValueError("Alpha003 target feed names must be unique")
        if self.p.cohort is None:
            raise ValueError("Alpha003TargetStrategy requires the exact shared cohort")
        if not isinstance(self.p.calendar_id, str) or not self.p.calendar_id:
            raise ValueError("Alpha003TargetStrategy requires a frozen calendar_id")
        if type(self.p.direction) is not int or self.p.direction not in (-1, 1):
            raise ValueError("direction must be exactly +1 or -1")
        authorized = frozenset(self.p.authorized_targets)
        if not authorized.issubset(set(target_ids)):
            raise ValueError("authorized_targets must be a subset of factor target feeds")

        if type(self.p.replay_mode) is not bool or type(self.p.execution_enabled) is not bool:
            raise TypeError("replay_mode and execution_enabled must be explicit booleans")
        if self.p.replay_mode and not self.p.execution_enabled:
            raise ValueError("replay_mode requires execution_enabled for a trading replay")
        if self.p.replay_mode and not self.p.cohort:
            raise ValueError("replay requires the sealed history-only cohort")
        if (
            self.p.execution_enabled
            and not self.p.replay_mode
            and (self.p.max_live_bar_age_seconds is None or self.p.max_future_skew_seconds is None)
        ):
            raise ValueError("live execution requires explicit factor freshness limits")
        if self.p.execution_enabled and not self.p.replay_mode:
            self._loss_guard_net_loss_threshold = _positive_decimal(
                self.p.loss_guard_net_loss_threshold,
                "loss_guard_net_loss_threshold",
            )
            age = self.p.loss_guard_max_observation_age_seconds
            if type(age) is not int or not 1 <= age <= 86_400:
                raise ValueError("live execution requires a positive loss observation age")
            self._loss_guard_max_observation_age_seconds = age
        else:
            # Replay and read-only live modes do not establish or require PnL.
            self._loss_guard_net_loss_threshold = None
            self._loss_guard_max_observation_age_seconds = None
        self._max_live_bar_age_seconds = _freshness_seconds(
            60.0 if self.p.max_live_bar_age_seconds is None else self.p.max_live_bar_age_seconds,
            "max_live_bar_age_seconds",
        )
        self._max_future_skew_seconds = _freshness_seconds(
            0.0 if self.p.max_future_skew_seconds is None else self.p.max_future_skew_seconds,
            "max_future_skew_seconds",
            allow_zero=True,
        )
        self._risk_policy = _risk_policy(self.p.risk_policy)
        self._quote_max_age_seconds = (
            None
            if self.p.quote_max_age_seconds is None
            else _positive_decimal(self.p.quote_max_age_seconds, "quote_max_age_seconds")
        )
        if (
            self._risk_policy is not None
            and self._quote_max_age_seconds is not None
            and self._quote_max_age_seconds != self._risk_policy.quote_max_age_seconds
        ):
            raise ValueError("quote_max_age_seconds must match the frozen risk_policy")
        self._max_query_age_seconds = (
            None
            if self.p.max_query_age_seconds is None
            else _positive_decimal(self.p.max_query_age_seconds, "max_query_age_seconds")
        )
        self._strategy_scope = self.p.strategy_scope
        if not isinstance(self._strategy_scope, str) or not self._strategy_scope:
            raise ValueError("strategy_scope must be explicit")
        self._account_scope = self.p.account_scope
        self._logical_run_id = self.p.logical_run_id
        source_kind = getattr(self.p, "source_kind", None)
        if source_kind is None:
            source_kind = "ALPHA003_GRID"
        lineage_prefix = "ALPHA003_GRID:trading-day-map-v1:"
        lineage_digest = source_kind[len(lineage_prefix) :] if type(source_kind) is str else ""
        if source_kind != "ALPHA003_GRID" and not (
            type(source_kind) is str
            and source_kind.startswith(lineage_prefix)
            and len(lineage_digest) == 64
            and all(character in "0123456789abcdef" for character in lineage_digest)
        ):
            raise ValueError("source_kind must be the internal trading-day lineage")
        self._source_kind = source_kind
        self._routes = self._normalize_routes(self.p.routes, target_ids)
        self._session_calendars = self.p.session_calendars or {}
        if not isinstance(self._session_calendars, Mapping):
            raise TypeError("session_calendars must map exact exchange IDs to calendars")
        self._replay_instruments = self.p.replay_instruments or {}
        if not isinstance(self._replay_instruments, Mapping):
            raise TypeError("replay_instruments must map target IDs to explicit metadata")
        self._replay_quotes = tuple(_replay_quote(value) for value in self.p.replay_quotes)
        self._replay_owners = {}
        self._orders_by_broker_ref = {}
        self.order_events = deque(maxlen=128)
        self.trade_events = deque(maxlen=128)
        self.last_execution_facts = None
        self._last_execution_facts_broker = None
        self._last_execution_facts_store = None
        self.last_order_plan: Optional[Alpha003OrderPlan] = None
        self.last_execution_block_reason: Optional[str] = None
        self._last_commission_idle_notice: Optional[Mapping[str, Any]] = None
        self._last_batch_id: Optional[str] = None
        self._last_signal_target: Optional[Alpha003TargetDecision] = None
        self._eligible_grid_count = 0
        self._counted_epoch_id: Optional[int] = None
        self._live_shadow_order_count = 0
        self._replay_order_count = 0
        self._control_refresh_stopped = False
        self._shutdown_requested = threading.Event()
        self._shutdown_ready_state = False
        self._shutdown_post_join_confirmed_state = False
        self._shutdown_engine_stop_requested = False
        self._shutdown_blocker_state: Optional[str] = "SHUTDOWN_NOT_REQUESTED"
        self._shutdown_post_join_blocker_state: Optional[str] = "SHUTDOWN_NOT_REQUESTED"
        self._last_shutdown_facts_id: Optional[str] = None
        self._last_session_close_at: Optional[datetime] = None
        self._last_decision_tape_batch_id: Optional[str] = None
        self._last_decision_tape_reference: Optional[Mapping[str, Any]] = None
        self._last_decision_tape_error: Optional[str] = None
        self._live_ready_callback_attempted = False
        self._live_ready_callback_completed = False
        self._live_ready_callback_failed = False
        self._live_ready_event_identity = None
        self._live_next_callback_attempted = False
        self._live_next_callback_completed = False
        self._live_next_callback_failed = False
        self._live_capacity_callback_count = 0
        self._live_capacity_callback_failed = False
        self._source_restart_marker = self.p.source_restart_marker
        self._source_predecessor = (
            None
            if self._source_restart_marker is None
            else self._source_restart_marker.prior_highwater
        )
        self._source_receipt_batch_id: Optional[str] = None
        self._source_receipt_tape_reference: Optional[Mapping[str, Any]] = None
        self._source_receipt_cache: Any = None
        self.source_continuity_failure_count = 0
        self.source_continuity_first_error: Optional[str] = None
        refresh_loop = self.p.control_refresh_loop
        if refresh_loop is not None and not callable(getattr(refresh_loop, "stop_and_join", None)):
            raise TypeError("control_refresh_loop must expose stop_and_join()")
        if refresh_loop is not None:
            binder = getattr(refresh_loop, "bind_strategy", None)
            if not callable(binder):
                raise TypeError("control_refresh_loop must expose bind_strategy(strategy)")
            binder(self)

        from backtrader.research.live import LiveFactorSet

        plan = make_alpha003_live_plan(
            target_ids,
            calendar_id=self.p.calendar_id,
            mode=self.p.factor_mode,
            direction=self.p.direction,
            preheat_bars=self.p.preheat_bars,
            max_pending_slots=self.p.max_pending_slots,
            max_window_bars=self.p.max_window_bars,
            wait_timeout_ns=self.p.wait_timeout_ns,
            max_live_bar_age_seconds=self._max_live_bar_age_seconds,
            max_future_skew_seconds=self._max_future_skew_seconds,
        )
        data_by_name = {data._name: data for data in self.datas}
        self.live_factors = LiveFactorSet.bind(plan, data_by_name, cohort=self.p.cohort)
        self._target_ids = target_ids
        self._authorized_targets = authorized
        self._product_keys = _product_key_mapping(self.p.product_keys, target_ids)
        self.last_target_decision: Optional[Alpha003TargetDecision] = None
        self.last_signal_block_reason: Optional[str] = "NO_COMPLETE_BATCH"
        self._data_by_target = data_by_name
        self._broker = self.broker
        self._coordinator = getattr(self.broker, "factor_execution_coordinator", None)
        if self.p.execution_enabled:
            if self._risk_policy is None:
                raise ValueError("execution_enabled requires every explicit risk-policy budget")
            if not self._account_scope or not self._logical_run_id:
                raise ValueError("execution requires explicit account_scope and logical_run_id")
            if self.p.replay_mode:
                from backtrader.brokers.factor_replay import CausalReplayBroker

                if not isinstance(self.broker, CausalReplayBroker):
                    raise ValueError("replay_mode requires CausalReplayBroker")
                if getattr(self.broker, "store", None) is not None:
                    raise ValueError("causal replay cannot carry an external Store route")
                if self._coordinator is not None:
                    raise ValueError("causal replay cannot use the live execution coordinator")
                if set(self._replay_instruments) != set(target_ids):
                    raise ValueError("replay_instruments must cover the exact factor target pool")
                if set(self._routes) != set(target_ids):
                    raise ValueError("routes must cover the exact replay target pool")
            else:
                self._validate_live_execution_binding()

    def _normalize_routes(
        self, value: Any, targets: Tuple[str, ...]
    ) -> Mapping[str, Tuple[str, str]]:
        if value is None:
            value = {}
        if not isinstance(value, Mapping):
            raise TypeError("routes must map each target to exact (InstrumentID, ExchangeID)")
        if set(value) - set(targets):
            raise ValueError("routes may only name declared target feeds")
        normalized = {}
        for target in targets:
            pair = value.get(target)
            if pair is None:
                continue
            if not isinstance(pair, (tuple, list)) or len(pair) != 2:
                raise ValueError("each route must be an exact (InstrumentID, ExchangeID) pair")
            instrument, exchange = pair
            _require_text(instrument, "route InstrumentID")
            _require_text(exchange, "route ExchangeID")
            normalized[target] = (instrument, exchange)
        return MappingProxyType(normalized)

    def _validate_live_execution_binding(self) -> None:
        from backtrader.brokers.btapibroker import BtApiBroker
        from backtrader.stores.registered_sim import RegisteredSimStore

        if not isinstance(self.broker, BtApiBroker):
            raise ValueError("live execution requires BtApiBroker")
        store = getattr(self.broker, "store", None)
        if not isinstance(store, RegisteredSimStore):
            raise ValueError("live execution requires RegisteredSimStore")
        if getattr(store, "registered_sim_route_id", None) != "simnow-registered-v1":
            raise ValueError("live execution requires the registered SimNow route")
        coordinator = self._coordinator
        if coordinator is None or getattr(coordinator, "broker", None) is not self.broker:
            raise ValueError("live execution requires the coordinator attached to this Broker")
        for name, expected in (
            ("account_scope", self._account_scope),
            ("strategy_scope", self._strategy_scope),
            ("logical_run_id", self._logical_run_id),
        ):
            if getattr(coordinator, name, None) != expected:
                raise ValueError("live coordinator %s mismatch" % name)
        if set(self._routes) != set(self._target_ids):
            raise ValueError("live routes must cover the exact factor target pool")

    def _clock_now(self) -> datetime:
        clock = getattr(self.cerebro, "live_bar_cohort_clock", None)
        if clock is None:
            raise ValueError("cohort strategy requires Cerebro's explicit UTC clock")
        getter = getattr(clock, "utc_now", None)
        if not callable(getter):
            raise ValueError("cohort clock must provide utc_now()")
        return _as_utc(getter(), "cohort clock UTC time")

    def _current_batch_snapshot(self):
        batch = self.p.cohort.current_batch()
        if batch is None:
            return None, None
        if _read(batch, "cohort_id") != _read(self.p.cohort, "cohort_id"):
            raise ValueError("current cohort batch identity changed")
        return batch, self.live_factors.snapshot()

    def _cursor_ordinal(self, batch: Any, *, is_new: bool) -> int:
        if self.p.replay_mode:
            return self._eligible_grid_count + (1 if is_new else 0)
        cursor = None
        if self._coordinator is not None:
            cursor = self._coordinator.grid_cursor(_read(self.p.cohort, "cohort_id"))
        if cursor is None:
            return self._eligible_grid_count + (1 if is_new else 0)
        ordinal = _read(cursor, "ordinal")
        if type(ordinal) is not int or ordinal < 1:
            raise ValueError("durable cohort cursor ordinal is invalid")
        if _read(cursor, "batch_id") == _read(batch, "batch_id"):
            return ordinal
        return ordinal + (1 if is_new else 0)

    def _update_target_decision(self, batch: Any, snapshot: Any, *, is_new: bool) -> Optional[int]:
        if batch is None or snapshot is None:
            return None
        mode = "REPLAY" if self.p.replay_mode else "LIVE"
        ordinal = self._cursor_ordinal(batch, is_new=is_new)
        policy_input = policy_input_from_shared_snapshot(
            batch,
            snapshot,
            required_targets=self._target_ids,
            authorized_targets=self._authorized_targets,
            product_keys=self._product_keys,
            execution_mode=mode,
            eligible_grid_index=ordinal,
            rebalance_every=self.p.rebalance_every,
        )
        preselection_reason = _preselection_block_reason(policy_input)
        if (
            is_new
            and preselection_reason is None
            and (self.p.replay_mode or self._coordinator is None)
        ):
            self._eligible_grid_count += 1
        decision = select_alpha003_targets(policy_input)
        self.last_target_decision = decision
        refresh_loop = self.p.control_refresh_loop
        publish_fee_priority = getattr(
            refresh_loop, "publish_commission_target_decision", None
        )
        if callable(publish_fee_priority):
            publish_fee_priority(decision)
        self.last_signal_block_reason = decision.reason
        # A target is actionable only on the grid that produced it. Keeping an
        # older target through a non-due/invalid grid would quietly turn the
        # five-grid rebalance cadence into a stale signal retry policy.
        self._last_signal_target = decision if decision.status == "TARGETS_READY" else None
        self._counted_epoch_id = policy_input.factor.epoch_id
        return ordinal if preselection_reason is None else None

    def _session_facts(self, batch: Any) -> Tuple[Optional[datetime], bool, Optional[str]]:
        try:
            close_at, reason = _session_close_from_batch(
                batch,
                data_by_target=self._data_by_target,
                product_keys=self._product_keys,
                routes=self._routes,
                session_calendars=self._session_calendars,
            )
        except Exception:
            # A failed source-calendar lookup blocks new risk, but should not
            # erase separately validated stop/hold reductions later in the
            # planner.
            return None, False, "SESSION_CLOSE_EVIDENCE_INVALID"
        final_check = getattr(self.p.cohort, "is_final_batch", None)
        if not callable(final_check):
            return close_at, False, reason or "FINAL_BATCH_EVIDENCE_UNAVAILABLE"
        try:
            run_end = final_check(batch)
        except Exception:
            return close_at, False, reason or "FINAL_BATCH_EVIDENCE_INVALID"
        if type(run_end) is not bool:
            return close_at, False, reason or "FINAL_BATCH_EVIDENCE_INVALID"
        return close_at, run_end, reason

    def _live_facts(self, now: datetime):
        from backtrader.stores.factor_execution_facts import (
            FactorExecutionTarget,
            project_factor_execution_facts,
        )

        # Never leave an older projection visible when this call cannot obtain
        # a coherent current Store/query-set view.
        self.last_execution_facts = None
        self._last_execution_facts_broker = None
        self._last_execution_facts_store = None
        self.last_execution_block_reason = None
        broker = self.broker
        store = getattr(broker, "store", None)
        if store is None:
            self.last_execution_block_reason = "EXECUTION_STORE_UNAVAILABLE"
            return None
        execution_enabled = getattr(self.p, "execution_enabled", None)
        if type(execution_enabled) is not bool:
            self.last_execution_block_reason = "EXECUTION_MODE_INVALID"
            return None
        if self._risk_policy is None and execution_enabled is True:
            self.last_execution_block_reason = "RISK_POLICY_REQUIRED"
            return None
        quote_max_age_seconds = self._quote_max_age_seconds
        query_max_age_seconds = self._max_query_age_seconds
        if self._risk_policy is not None:
            if quote_max_age_seconds is None:
                quote_max_age_seconds = self._risk_policy.quote_max_age_seconds
            if query_max_age_seconds is None:
                query_max_age_seconds = self._risk_policy.max_state_age_seconds
        if quote_max_age_seconds is None or query_max_age_seconds is None:
            self.last_execution_block_reason = "LIVE_FACT_AGE_BOUNDS_REQUIRED"
            return None
        try:
            quote_max_age_seconds = _positive_decimal(
                quote_max_age_seconds, "quote_max_age_seconds"
            )
            query_max_age_seconds = _positive_decimal(
                query_max_age_seconds, "max_query_age_seconds"
            )
        except (TypeError, ValueError):
            self.last_execution_block_reason = "LIVE_FACT_AGE_BOUNDS_INVALID"
            return None
        targets = tuple(
            FactorExecutionTarget(
                target_id=target,
                instrument=self._routes[target][0],
                exchange=self._routes[target][1],
                data=self._data_by_target[target],
            )
            for target in self._target_ids
            if target in self._routes
        )
        if len(targets) != len(self._target_ids):
            self.last_execution_block_reason = "LIVE_ROUTE_SET_INCOMPLETE"
            return None
        execution_target_ids = tuple(
            target_id for target_id in self._target_ids if target_id in self._authorized_targets
        )
        refresh_loop_execution_ids = getattr(
            self.p.control_refresh_loop, "execution_target_ids", execution_target_ids
        )
        if tuple(refresh_loop_execution_ids) != execution_target_ids:
            self.last_execution_block_reason = "LIVE_EXECUTION_TARGET_SET_MISMATCH"
            return None
        refresh_loop = getattr(self.p, "control_refresh_loop", None)
        commission_required_override = getattr(
            refresh_loop, "commission_required_for_open", None
        )
        if commission_required_override is not None and type(commission_required_override) is not bool:
            self.last_execution_block_reason = "COMMISSION_REQUIRED_FOR_OPEN_INVALID"
            return None
        commission_required_for_open = (
            execution_enabled is True or commission_required_override is True
        )

        def project_current_snapshot():
            return project_factor_execution_facts(
                store,
                broker,
                targets=targets,
                account_scope=self._account_scope,
                strategy_scope=self._strategy_scope,
                now=now,
                query_set=getattr(
                    getattr(self.p.control_refresh_loop, "last_receipt", None),
                    "query_set",
                    None,
                ),
                quote_max_age=timedelta(seconds=float(quote_max_age_seconds)),
                max_query_age=timedelta(seconds=float(query_max_age_seconds)),
                execution_target_ids=execution_target_ids,
                commission_identity_by_target=getattr(
                    refresh_loop, "commission_identity_by_target", None
                ),
                commission_required_for_open=commission_required_for_open,
            )

        try:
            projection_scope = getattr(refresh_loop, "strategy_fact_projection_scope", None)
            if callable(projection_scope):
                with projection_scope() as acquired:
                    if acquired is not True:
                        self.last_execution_block_reason = "EXECUTION_FACT_REFRESH_IN_PROGRESS"
                        return None
                    facts = project_current_snapshot()
            else:
                facts = project_current_snapshot()
        except (OverflowError, TypeError, ValueError, RuntimeError):
            self.last_execution_block_reason = "EXECUTION_FACT_PROJECTION_UNAVAILABLE"
            return None
        self.last_execution_facts = facts
        self._last_execution_facts_broker = broker
        self._last_execution_facts_store = store
        self.last_execution_block_reason = None
        return facts

    def _refresh_run_loss_guard(self, facts: Any, now: datetime):
        """Seed once, then advance the persisted run PnL latch from one full query."""
        if self.p.execution_enabled is not True or self.p.replay_mode is True:
            return None, None

        from backtrader.stores.execution_decision_journal import (
            ExecutionDecisionJournalError,
            ExecutionRunLossGuardContext,
            ExecutionRunLossGuardSnapshot,
        )
        from backtrader.stores.factor_execution import FactorExecutionError
        from backtrader.stores.factor_execution_facts import (
            FactorExecutionAccountFacts,
            FactorExecutionFacts,
            FactorExecutionQuerySetFacts,
            FactorExecutionRefreshReceipt,
        )

        try:
            now_utc = _as_utc(now, "loss guard observation clock")
        except (TypeError, ValueError) as error:
            raise FactorExecutionError("RUN_LOSS_GUARD_CLOCK_INVALID") from error
        refresh_loop = getattr(self.p, "control_refresh_loop", None)
        if refresh_loop is None:
            raise FactorExecutionError("RUN_LOSS_GUARD_REFRESH_BINDING_REQUIRED")
        complete_check = getattr(type(refresh_loop), "_receipt_complete", None)
        if not callable(complete_check):
            raise FactorExecutionError("RUN_LOSS_GUARD_REFRESH_BINDING_REQUIRED")

        coordinator = self._coordinator
        if coordinator is None:
            raise FactorExecutionError("RUN_LOSS_GUARD_COORDINATOR_UNAVAILABLE")
        journal = coordinator.journal
        try:
            saved = journal.run_loss_guard(
                self._account_scope,
                self._strategy_scope,
                self._logical_run_id,
            )
        except ExecutionDecisionJournalError as error:
            raise FactorExecutionError(error.code) from error

        account = getattr(facts, "account", None) if facts is not None else None
        if saved is None:
            if (
                type(account) is not FactorExecutionAccountFacts
                or type(account.trading_day) is not str
            ):
                return None, "RUN_LOSS_ACCOUNT_PNL_UNQUALIFIED"
            try:
                context = ExecutionRunLossGuardContext(
                    account_scope=self._account_scope,
                    strategy_scope=self._strategy_scope,
                    logical_run_id=self._logical_run_id,
                    trading_day=account.trading_day,
                    currency="CNY",
                    pnl_basis=RUN_LOSS_PNL_BASIS,
                )
            except ExecutionDecisionJournalError:
                return None, "RUN_LOSS_ACCOUNT_TRADING_DAY_MISMATCH"
        else:
            if type(saved) is not ExecutionRunLossGuardSnapshot:
                raise FactorExecutionError("RUN_LOSS_GUARD_STATE_INVALID")
            context = saved.context
            if type(context) is not ExecutionRunLossGuardContext:
                raise FactorExecutionError("RUN_LOSS_GUARD_STATE_INVALID")

        try:
            self._coordinator.run_loss_guard(context)
        except FactorExecutionError as error:
            if error.code in _RUN_LOSS_OPEN_REJECTION_CODES:
                return None, error.code
            raise

        if saved is not None and (
            saved.net_loss_threshold != self._loss_guard_net_loss_threshold
            or saved.max_observation_age_seconds
            != self._loss_guard_max_observation_age_seconds
        ):
            return None, "RUN_LOSS_GUARD_POLICY_CONFLICT"
        if (
            type(facts) is not FactorExecutionFacts
            or type(account) is not FactorExecutionAccountFacts
        ):
            return None, "RUN_LOSS_ACCOUNT_PNL_UNQUALIFIED"

        receipt = getattr(refresh_loop, "last_receipt", None)
        if type(receipt) is not FactorExecutionRefreshReceipt:
            return None, "RUN_LOSS_ACCOUNT_REFRESH_INCOMPLETE"
        if complete_check(receipt) is not True:
            return None, "RUN_LOSS_ACCOUNT_REFRESH_INCOMPLETE"
        query_set = receipt.query_set
        if type(query_set) is not FactorExecutionQuerySetFacts:
            return None, "RUN_LOSS_ACCOUNT_QUERYSET_MISMATCH"
        if (
            facts.account_scope != self._account_scope
            or facts.strategy_scope != self._strategy_scope
            or facts.query_set_id != query_set.query_set_id
            or account.account_scope != self._account_scope
            or account.account_fingerprint != query_set.account_fingerprint
            or account.connection_generation != query_set.connection_generation
            or account.trading_day != query_set.trading_day
        ):
            return None, "RUN_LOSS_ACCOUNT_QUERYSET_MISMATCH"
        if (
            account.trading_day != context.trading_day
            or query_set.trading_day != context.trading_day
        ):
            # The policy's first TradingDay is immutable across restarts and
            # CTP day changes. Never create a fresh baseline implicitly.
            return None, "RUN_LOSS_ACCOUNT_TRADING_DAY_MISMATCH"
        if account.currency != "CNY" or context.currency != "CNY":
            return None, "RUN_LOSS_ACCOUNT_CURRENCY_MISMATCH"
        if (
            account.total_net_pnl_available is not True
            or account.total_net_pnl_reason is not None
            or type(account.total_net_pnl) is not Decimal
            or not account.total_net_pnl.is_finite()
        ):
            return None, "RUN_LOSS_ACCOUNT_PNL_UNQUALIFIED"

        try:
            receipt_at = _as_utc(receipt.completed_at, "loss guard refresh completion")
            query_set_at = _as_utc(query_set.completed_at_utc, "loss guard query-set completion")
            account_at = _as_utc(account.available_at, "loss guard account completion")
            receipt_started = _as_utc(receipt.started_at, "loss guard refresh start")
        except (TypeError, ValueError):
            return None, "RUN_LOSS_ACCOUNT_ASOF_INVALID"
        max_age = timedelta(seconds=self._loss_guard_max_observation_age_seconds)
        if (
            receipt_started > receipt_at
            or query_set_at > receipt_at
            or receipt_at > now_utc
            or query_set_at > now_utc
            or account_at > now_utc
            or account_at > query_set_at
            or now_utc - receipt_at > max_age
            or now_utc - query_set_at > max_age
            or now_utc - account_at > max_age
        ):
            return None, "RUN_LOSS_OBSERVATION_STALE"

        try:
            if saved is None:
                self._coordinator.enable_run_loss_guard(
                    context,
                    account,
                    net_loss_threshold=self._loss_guard_net_loss_threshold,
                    max_observation_age_seconds=self._loss_guard_max_observation_age_seconds,
                )
            elif saved.latest_observation_id != account.snapshot_id:
                # The journal accepts an exact latest-ID replay idempotently;
                # the caller skips it and records only newly queried IDs.
                self._coordinator.record_run_loss_observation(context, account)
        except FactorExecutionError as error:
            if error.code in _RUN_LOSS_OPEN_REJECTION_CODES:
                return None, error.code
            raise
        return context, None

    def _replay_instrument_facts(self, target_id: str, now: datetime) -> Alpha003InstrumentRiskFact:
        value = self._replay_instruments[target_id]
        if isinstance(value, Alpha003InstrumentRiskFact):
            instrument, exchange = self._routes[target_id]
            if (
                value.target_id != target_id
                or value.instrument != instrument
                or value.exchange != exchange
            ):
                raise ValueError("replay instrument facts do not match their exact target route")
            return value
        if not isinstance(value, Mapping):
            raise TypeError("replay instrument metadata must be typed or an immutable mapping")
        instrument, exchange = self._routes[target_id]
        if value.get("instrument") != instrument or value.get("exchange") != exchange:
            raise ValueError("replay instrument metadata does not match its exact route")
        return Alpha003InstrumentRiskFact(
            target_id=target_id,
            instrument=instrument,
            exchange=exchange,
            snapshot_id=value.get("snapshot_id"),
            available_at=value.get("available_at"),
            trading_permitted=value.get("trading_permitted"),
            multiplier=_decimal_or_none(value.get("multiplier")),
            long_margin_per_hand=_decimal_or_none(value.get("long_margin_per_hand")),
            short_margin_per_hand=_decimal_or_none(value.get("short_margin_per_hand")),
            tick_size=_decimal_or_none(value.get("tick_size")),
            lower_limit=_decimal_or_none(value.get("lower_limit")),
            upper_limit=_decimal_or_none(value.get("upper_limit")),
            route_permitted=value.get("trading_permitted"),
        )

    def _latest_replay_quote(
        self, instrument: str, exchange: str, *, available_by: datetime
    ) -> Optional[Alpha003ReplayQuoteFact]:
        available = tuple(
            quote
            for quote in self._replay_quotes
            if (quote.instrument, quote.exchange) == (instrument, exchange)
            and quote.available_at <= available_by
        )
        if not available:
            return None
        return max(
            available,
            key=lambda quote: (quote.available_at, quote.event_time, quote.quote_id),
        )

    def _replay_active_order_snapshot(self) -> Tuple[Tuple[Any, ...], bool]:
        """Read BackBroker's submitted and pending queues as one bounded snapshot.

        ``get_orders_open`` exposes only ``pending``. A newly submitted order
        can still be in ``submitted`` while margin checks are deferred, so an
        unreadable or absent queue must not be interpreted as an empty book.
        Repeated references to the same object are one order; conflicting
        objects with a repeated broker reference remain visible and make the
        snapshot incomplete.
        """

        orders = []
        seen_objects = set()
        seen_refs = {}
        complete = True
        missing = object()
        for queue_name in ("submitted", "pending"):
            try:
                queue = getattr(self.broker, queue_name, missing)
                if queue is missing or queue is None:
                    return tuple(orders), False
                queued_orders = tuple(queue)
            except Exception:
                return tuple(orders), False
            for order in queued_orders:
                if order is None:
                    complete = False
                    continue
                identity = id(order)
                if identity in seen_objects:
                    continue
                seen_objects.add(identity)
                try:
                    order_ref = order.ref
                except Exception:
                    order_ref = None
                if type(order_ref) is int and order_ref > 0:
                    previous = seen_refs.get(order_ref)
                    if previous is not None and previous is not order:
                        complete = False
                    else:
                        seen_refs[order_ref] = order
                else:
                    complete = False
                # Keep conflicting refs in the snapshot. Dropping either could
                # conceal an active order; the incomplete flag prevents the
                # resulting projection from authorizing OPEN or shutdown.
                orders.append(order)
        return tuple(orders), complete

    def _replay_planning_input(
        self,
        *,
        batch: Any,
        now: datetime,
        risk_evidence_at: datetime,
        session_close_at: Optional[datetime],
        run_end: bool,
        ordinal: Optional[int],
        target_decision: Optional[Alpha003TargetDecision],
    ) -> Alpha003OrderPlanningInput:
        # Capture both BackBroker queues once, before projecting any
        # position/account totals. Pending-order economics are not sufficient
        # here to separate already-filled exposure from the unfilled remainder.
        broker_working_orders, order_snapshot_complete = (
            self._replay_active_order_snapshot()
        )
        open_order_budget_unavailable = bool(broker_working_orders) or not order_snapshot_complete
        positions = []
        instruments = []
        margin_used = Decimal(0)
        notional_used = Decimal(0)
        stop_loss = Decimal(0)
        finance_complete = True
        for target_id in self._target_ids:
            instrument = self._replay_instrument_facts(target_id, now)
            instruments.append(instrument)
            position = self.broker.getposition(self._data_by_target[target_id])
            quantity = _exact_hands(getattr(position, "size", None))
            owner = self._replay_owners.get(target_id)
            if quantity is not None and quantity != 0:
                owner_intent = (
                    _replay_exact_text(owner.get("owner_intent_id"))
                    if isinstance(owner, Mapping)
                    else None
                )
                if owner_intent is None:
                    owner_scope = owner_intent = None
                    average = _decimal_or_none(getattr(position, "price", None))
                    stop = held = None
                else:
                    owner_scope = self._strategy_scope
                    raw_stop = _decimal_or_none(owner.get("stop_price"))
                    stop = raw_stop if raw_stop is not None and raw_stop > 0 else None
                    raw_held = owner.get("held_eligible_bars")
                    held = (
                        raw_held
                        if type(raw_held) is int and raw_held >= 0
                        else None
                    )
                    average = _decimal_or_none(getattr(position, "price", None))
                if (
                    instrument.multiplier is None
                    or average is None
                    or stop is None
                    or instrument.long_margin_per_hand is None
                    or instrument.short_margin_per_hand is None
                ):
                    finance_complete = False
                else:
                    side_margin = (
                        instrument.long_margin_per_hand
                        if quantity > 0
                        else instrument.short_margin_per_hand
                    )
                    margin_used += abs(quantity) * side_margin
                    notional_used += abs(quantity) * average * instrument.multiplier
                    stop_loss += abs(quantity) * abs(average - stop) * instrument.multiplier
            else:
                owner_scope = owner_intent = None
                average = stop = None
                held = None
                quantity = 0 if quantity == 0 else None
            positions.append(
                Alpha003PositionFact(
                    target_id=target_id,
                    instrument=instrument.instrument,
                    exchange=instrument.exchange,
                    quantity=quantity,
                    snapshot_id="backbroker-position-%s" % target_id,
                    available_at=now,
                    owner_strategy_scope=owner_scope,
                    owner_intent_id=owner_intent,
                    average_price=average,
                    stop_price=stop,
                    held_eligible_bars=held,
                )
            )
        quotes = []
        for target_id in self._target_ids:
            risk = next(item for item in instruments if item.target_id == target_id)
            quote = self._latest_replay_quote(risk.instrument, risk.exchange, available_by=now)
            if quote is None:
                continue
            quotes.append(
                Alpha003QuoteFact(
                    instrument=quote.instrument,
                    exchange=quote.exchange,
                    source_ref=quote.source_ref,
                    metadata_snapshot_id=risk.snapshot_id,
                    generation=1,
                    sequence=None,
                    event_time=quote.event_time,
                    available_at=quote.available_at,
                    bid=quote.bid,
                    ask=quote.ask,
                    bid_size=None,
                    ask_size=None,
                    tick_size=risk.tick_size,
                    lower_limit=risk.lower_limit,
                    upper_limit=risk.upper_limit,
                    quality="GOOD",
                    evidence_source="REPLAY_TAPE",
                )
            )
        # BackBroker positions already include any fills. Its pending queue
        # does not give this replay projection enough authoritative economics
        # to reserve the unfilled remainder without risking double-counting
        # those fills (or omitting fees/contract margin). Keep that limitation
        # explicit: any live pending order makes new OPEN capacity unavailable.
        # Mapped orders remain in the normal fact set so independently
        # authorized CANCEL/CLOSE planning can continue.
        working_orders = []
        order_cancel_route_matches = []
        replay_order_states = {
            "CREATED": "PREPARED",
            "SUBMITTED": "DISPATCHING",
            "ACCEPTED": "ACCEPTED",
            "PARTIAL": "PARTIAL",
            "UNKNOWN": "UNKNOWN",
            "CANCEL_PENDING": "CANCEL_PENDING",
        }
        open_position_routes = {
            (item.instrument, item.exchange)
            for item in positions
            if item.quantity not in (None, 0)
        }
        authorized_targets = tuple(
            target_id
            for target_id in self._target_ids
            if target_id in getattr(self, "_authorized_targets", ())
        )
        reduction_order_snapshot_complete = order_snapshot_complete
        for order in broker_working_orders:
            try:
                order_data = order.data
            except Exception:
                order_data = None
            matching_targets = tuple(
                name for name, data in self._data_by_target.items() if data is order_data
            )
            # An unmapped or ambiguously mapped order still blocks opening
            # capacity above. It cannot authorize an action or prove that a
            # risk-reducing CLOSE is independent: order.info route labels are
            # caller metadata, and this feed identity has no mapped target.
            if len(matching_targets) != 1:
                reduction_order_snapshot_complete = False
                continue
            target_id = matching_targets[0]
            info = getattr(order, "info", None)
            if not isinstance(info, Mapping):
                info = {}
            try:
                status_name = order.getstatusname()
            except Exception:
                status_name = None
            status = (
                replay_order_states.get(status_name.upper(), "UNKNOWN")
                if type(status_name) is str
                else "UNKNOWN"
            )
            raw_effect = info.get("factor_position_effect")
            effect = (
                raw_effect
                if type(raw_effect) is str and raw_effect in {"OPEN", "CLOSE"}
                else None
            )
            owner_id = _replay_owner_intent_id(info)
            owner_scope = _replay_exact_text(info.get("factor_strategy_scope"))
            info_instrument = _replay_exact_text(info.get("instrument_id"))
            info_exchange = _replay_exact_text(info.get("exchange_id"))
            route_instrument, route_exchange = self._routes[target_id]
            route_matches = (
                info_instrument == route_instrument and info_exchange == route_exchange
            )
            if not route_matches and (
                (route_instrument, route_exchange) in open_position_routes
                or (info_instrument, info_exchange) in open_position_routes
            ):
                reduction_order_snapshot_complete = False
            try:
                remaining = _exact_hands(getattr(order.executed, "remsize", None))
            except Exception:
                remaining = None
            try:
                created_size = _exact_hands(getattr(order.created, "size", None))
                executed_size = _exact_hands(getattr(order.executed, "size", None))
            except Exception:
                created_size = executed_size = None
            try:
                is_buy = order.isbuy()
                side = "BUY" if is_buy is True else "SELL" if is_buy is False else None
            except Exception:
                side = None
            expected_sign = 1 if side == "BUY" else -1 if side == "SELL" else 0
            if (
                created_size is None
                or created_size == 0
                or executed_size is None
                or remaining is None
                or remaining == 0
                or expected_sign == 0
                or created_size * expected_sign <= 0
                or remaining * expected_sign <= 0
                or abs(remaining) > abs(created_size)
                or executed_size + remaining != created_size
            ):
                remaining = None
            try:
                order_ref = order.ref
            except Exception:
                order_ref = None
            working_orders.append(
                Alpha003WorkingOrderFact(
                    target_id=target_id,
                    instrument=route_instrument,
                    exchange=route_exchange,
                    order_ref=(
                        owner_id
                        or (str(order_ref) if type(order_ref) is int else "unknown-order")
                    ),
                    broker_order_ref=(
                        order_ref if type(order_ref) is int and order_ref > 0 else None
                    ),
                    state=status,
                    side=side,
                    position_effect=effect,
                    remaining_quantity=abs(remaining) if remaining is not None else None,
                    owner_strategy_scope=owner_scope,
                    owner_intent_id=owner_id,
                )
            )
            order_cancel_route_matches.append(route_matches)
        order_cancel_ready = bool(working_orders) and order_snapshot_complete and all(
            order.owner_strategy_scope == self._strategy_scope
            and order.owner_intent_id is not None
            and order.broker_order_ref is not None
            and order.remaining_quantity is not None
            and order.remaining_quantity > 0
            and order.side in {"BUY", "SELL"}
            and order.position_effect == "OPEN"
            and order.state in {"ACCEPTED", "PARTIAL"}
            and order.target_id in authorized_targets
            and route_matches
            for order, route_matches in zip(working_orders, order_cancel_route_matches)
        )
        cash = _decimal_or_none(self.broker.getcash())
        value = _decimal_or_none(self.broker.getvalue())
        route_ok = bool(instruments) and all(item.trading_permitted is True for item in instruments)
        account = Alpha003AccountRiskFact(
            account_scope=self._account_scope,
            snapshot_id="backbroker-account-%s" % _time_key(now),
            available_at=now,
            route_permitted=route_ok,
            available_margin=(
                cash
                if not open_order_budget_unavailable and cash is not None and cash >= 0
                else None
            ),
            used_margin=(
                margin_used
                if not open_order_budget_unavailable and finance_complete
                else None
            ),
            current_notional=(
                notional_used
                if not open_order_budget_unavailable and finance_complete
                else None
            ),
            current_worst_case_loss=(
                stop_loss
                if not open_order_budget_unavailable and finance_complete
                else None
            ),
            cash=cash,
            equity=value,
        )
        valid_metadata = all(
            item.trading_permitted is True
            and item.multiplier is not None
            and item.long_margin_per_hand is not None
            and item.short_margin_per_hand is not None
            and item.tick_size is not None
            and item.lower_limit is not None
            and item.upper_limit is not None
            for item in instruments
        )
        ordinary_open_facts_ready = (
            route_ok
            and valid_metadata
            and finance_complete
            and cash is not None
            and value is not None
        )
        open_risk_blockers = (
            ("REPLAY_RISK_FACTS_UNAVAILABLE",)
            if not ordinary_open_facts_ready
            else ("REPLAY_WORKING_ORDER_SNAPSHOT_UNAVAILABLE",)
            if not order_snapshot_complete
            else ("REPLAY_WORKING_ORDER_BUDGET_UNAVAILABLE",)
            if open_order_budget_unavailable
            else ("REPLAY_EXECUTION_TARGET_SET_EMPTY",)
            if not authorized_targets
            else ()
        )
        return Alpha003OrderPlanningInput(
            strategy_scope=self._strategy_scope,
            evaluated_at=now,
            risk_evidence_available_at=risk_evidence_at,
            session_close_at=session_close_at,
            run_end=run_end,
            risk_policy=self._risk_policy,
            account=account,
            positions=tuple(positions),
            working_orders=tuple(working_orders),
            quotes=tuple(quotes),
            instruments=tuple(instruments),
            target_decision=target_decision,
            run_order_intents_used=self._replay_order_count,
            eligible_grid_ordinal=ordinal,
            risk_reduction_ready=(
                route_ok
                and reduction_order_snapshot_complete
                and bool(authorized_targets)
            ),
            risk_reduction_blockers=(
                ()
                if route_ok and reduction_order_snapshot_complete and authorized_targets
                else ("REPLAY_INSTRUMENT_NOT_PERMITTED",)
                if not route_ok
                else ("REPLAY_WORKING_ORDER_CONFLICT_UNAVAILABLE",)
                if not reduction_order_snapshot_complete
                else ("REPLAY_EXECUTION_TARGET_SET_EMPTY",)
            ),
            open_risk_ready=(
                ordinary_open_facts_ready
                and not open_order_budget_unavailable
                and bool(authorized_targets)
            ),
            open_risk_blockers=open_risk_blockers,
            order_cancel_ready=order_cancel_ready,
            order_cancel_blockers=(
                ()
                if order_cancel_ready
                else ("REPLAY_ORDER_SNAPSHOT_UNAVAILABLE",)
                if not order_snapshot_complete
                else ("REPLAY_ORDER_OWNERSHIP_UNAVAILABLE",)
                if open_order_budget_unavailable
                else ("REPLAY_EXECUTION_TARGET_SET_EMPTY",)
                if not authorized_targets
                else ()
            ),
            execution_target_ids=authorized_targets if authorized_targets else None,
            evidence_source="CAUSAL_REPLAY",
        )

    def _replay_now(self) -> datetime:
        floor = self.broker.current_decision_floor()
        now = self._clock_now()
        if now < floor:
            raise ValueError("replay clock precedes the bound source availability")
        return now

    def _update_replay_holding_age(self, ordinal: Optional[int]) -> None:
        if ordinal is None:
            return
        for owner in self._replay_owners.values():
            entry = owner.get("entry_grid_ordinal")
            if type(entry) is int:
                owner["held_eligible_bars"] = max(0, ordinal - entry)

    def _dispatch_replay_actions(self, plan: Alpha003OrderPlan, batch: Any) -> None:
        if not self.p.execution_enabled or plan.status != "READY":
            return
        for leg, action in enumerate(plan.actions):
            if action.action == "CANCEL":
                order = self._find_order_object(action)
                if order is None:
                    self.last_execution_block_reason = "CANCEL_ORDER_OBJECT_UNAVAILABLE"
                    return
                self.cancel(order)
                self._replay_order_count += 1
                continue
            data = self._data_by_target[action.target_id]
            replay_owner_id = None
            if action.position_effect == "OPEN":
                seed = "%s|%s|%s|%s|%s" % (
                    self._logical_run_id,
                    _read(batch, "batch_id"),
                    action.instrument,
                    action.side,
                    leg,
                )
                replay_owner_id = "replay-" + hashlib.sha256(seed.encode("utf-8")).hexdigest()
            info = {
                "instrument_id": action.instrument,
                "exchange_id": action.exchange,
                "factor_position_effect": action.position_effect,
                "offset": action.offset,
                "factor_strategy_scope": self._strategy_scope,
                "factor_entry_grid_ordinal": action.entry_grid_ordinal,
                "factor_stop_price": (
                    str(action.planned_stop_price)
                    if action.planned_stop_price is not None
                    else None
                ),
                "replay_owner_intent_id": replay_owner_id,
                "replay_signal_batch_id": (
                    self._last_signal_target.batch_id
                    if self._last_signal_target is not None
                    else None
                ),
                "replay_quote_id": (
                    quote.quote_id
                    if (
                        quote := self._latest_replay_quote(
                            action.instrument,
                            action.exchange,
                            available_by=action.decision_available_at,
                        )
                    )
                    is not None
                    else None
                ),
            }
            method = self.buy if action.side == "BUY" else self.sell
            order = method(
                data=data,
                size=action.quantity,
                price=float(action.limit_price) if action.limit_price is not None else None,
                exectype=bt.Order.Limit if action.limit_price is not None else bt.Order.Market,
                decision_available_at=action.decision_available_at,
                **info,
            )
            if order is not None:
                self._orders_by_broker_ref[order.ref] = order
                self._replay_order_count += 1

    def _update_replay_shutdown_state(self) -> None:
        """Confirm only this strategy's actual local positions and orders."""

        self._shutdown_ready_state = False
        self._shutdown_blocker_state = "SHUTDOWN_NOT_REQUESTED"
        self._last_shutdown_facts_id = None
        if not self._shutdown_requested.is_set():
            return
        positions = []
        for target_id in self._target_ids:
            position = self.broker.getposition(self._data_by_target[target_id])
            quantity = _exact_hands(getattr(position, "size", None))
            if quantity is None:
                self._shutdown_ready_state = False
                self._shutdown_blocker_state = "REPLAY_SHUTDOWN_POSITION_UNAVAILABLE"
                return
            if quantity:
                owner = self._replay_owners.get(target_id)
                owner_intent_id = (
                    _replay_exact_text(owner.get("owner_intent_id"))
                    if isinstance(owner, Mapping)
                    else None
                )
                if (
                    not isinstance(owner, Mapping)
                    or owner_intent_id is None
                    or (stop_price := _decimal_or_none(owner.get("stop_price"))) is None
                    or stop_price <= 0
                ):
                    self._shutdown_ready_state = False
                    self._shutdown_blocker_state = (
                        "REPLAY_SHUTDOWN_POSITION_OWNERSHIP_UNAVAILABLE:" + target_id
                    )
                    return
                positions.append((target_id, quantity))

        if self._risk_policy is None:
            self._shutdown_ready_state = False
            self._shutdown_blocker_state = "RISK_POLICY_REQUIRED"
            return
        if positions and self._risk_policy.run_end_policy == "CLOSE_ALL":
            self._shutdown_ready_state = False
            self._shutdown_blocker_state = "REPLAY_SHUTDOWN_POSITION_OPEN:" + positions[0][0]
            return

        orders, order_snapshot_complete = self._replay_active_order_snapshot()
        if not order_snapshot_complete:
            self._shutdown_blocker_state = "REPLAY_SHUTDOWN_ORDER_SNAPSHOT_UNAVAILABLE"
            return
        for order in orders:
            info = getattr(order, "info", None)
            if not isinstance(info, Mapping):
                info = {}
            owner_scope = info.get("factor_strategy_scope")
            owner_scope = _replay_exact_text(owner_scope)
            if owner_scope is None:
                self._shutdown_blocker_state = "REPLAY_SHUTDOWN_ORDER_OWNERSHIP_UNAVAILABLE"
                return
            if owner_scope != self._strategy_scope:
                continue
            try:
                order_data = order.data
            except Exception:
                order_data = None
            matching_targets = tuple(
                name for name, data in self._data_by_target.items() if data is order_data
            )
            if len(matching_targets) != 1:
                self._shutdown_blocker_state = "REPLAY_SHUTDOWN_ORDER_OWNERSHIP_UNAVAILABLE"
                return
            target_id = matching_targets[0]
            owner_id = _replay_owner_intent_id(info)
            instrument = _replay_exact_text(info.get("instrument_id"))
            exchange = _replay_exact_text(info.get("exchange_id"))
            if (
                owner_id is None
                or instrument != self._routes[target_id][0]
                or exchange != self._routes[target_id][1]
            ):
                self._shutdown_blocker_state = "REPLAY_SHUTDOWN_ORDER_OWNERSHIP_UNAVAILABLE"
                return
            try:
                status_name = order.getstatusname()
            except Exception:
                status_name = None
            if type(status_name) is not str or status_name.upper() not in {
                "CREATED",
                "SUBMITTED",
                "ACCEPTED",
                "PARTIAL",
            }:
                self._shutdown_blocker_state = "REPLAY_SHUTDOWN_ORDER_STATE_UNAVAILABLE"
                return
            self._shutdown_blocker_state = "REPLAY_SHUTDOWN_ORDER_ACTIVE"
            return

        self._shutdown_ready_state = True
        self._shutdown_blocker_state = None
        self._last_shutdown_facts_id = "backbroker-local"

    def _refresh_live_shutdown_confirmation(self) -> None:
        if not self._shutdown_requested.is_set() or self.p.replay_mode:
            return
        try:
            facts = self._live_facts(self._clock_now())
        except (TypeError, ValueError, RuntimeError):
            self._shutdown_ready_state = False
            self._shutdown_blocker_state = "SHUTDOWN_FACTS_UNAVAILABLE"
            return
        self._update_shutdown_state(facts, self.last_order_plan)

    def _find_order_object(self, action: Alpha003OrderAction):
        ref = action.broker_order_ref
        if ref is None:
            return None
        order = self._orders_by_broker_ref.get(ref)
        if order is None:
            orders = getattr(self.broker, "orders", None)
            if isinstance(orders, Mapping):
                order = orders.get(ref)
        if order is None:
            for candidate in self.broker.get_orders_open(safe=False):
                if candidate.ref == ref:
                    order = candidate
                    break
        if order is None or not order.alive():
            return None
        info = order.info
        if (
            info.get("instrument_id") != action.instrument
            or info.get("exchange_id") != action.exchange
        ):
            return None
        return order

    def _order_intents(self, plan: Alpha003OrderPlan, batch: Any):
        from backtrader.stores.execution_decision_journal import ExecutionIntentKey

        keys = []
        economics = []
        candidate = plan.open_risk_candidate
        candidate_legs = (
            {item.target_id: item for item in candidate.legs} if candidate is not None else {}
        )
        batch_id = _read(batch, "batch_id") if batch is not None else None
        if candidate is not None and (
            candidate.strategy_scope != self._strategy_scope or candidate.batch_id != batch_id
        ):
            raise ValueError("OPEN risk candidate is bound to another strategy batch")
        for leg, action in enumerate(plan.actions):
            keys.append(
                ExecutionIntentKey(
                    action=action.action,
                    instrument=action.instrument,
                    side=action.side,
                    position_effect=action.position_effect,
                    leg=leg,
                )
            )
            economic = {
                "target_id": action.target_id,
                "instrument": action.instrument,
                "instrument_id": action.instrument,
                "exchange": action.exchange,
                "side": action.side,
                "position_effect": action.position_effect,
                "quantity": action.quantity,
                "limit_price": str(action.limit_price) if action.limit_price is not None else None,
                "offset": action.offset,
                "reason": action.reason,
                "batch_id": _read(batch, "batch_id") if batch is not None else None,
            }
            if action.action == "SUBMIT" and action.position_effect == "OPEN" and candidate:
                risk_leg = candidate_legs.get(action.target_id)
                if risk_leg is None or len(candidate_legs) != len(candidate.legs):
                    raise ValueError("OPEN action is missing its exact planner risk candidate")
                if (
                    risk_leg.instrument != action.instrument
                    or risk_leg.exchange != action.exchange
                    or risk_leg.side != action.side
                    or risk_leg.quantity != action.quantity
                    or risk_leg.entry_price != action.limit_price
                    or risk_leg.stop_price != action.planned_stop_price
                ):
                    raise ValueError("OPEN action differs from its planner risk candidate")
                economic["open_risk_candidate"] = _open_risk_leg_candidate_payload(risk_leg)
            if action.position_date is not None:
                economic.update(
                    position_side=action.position_side,
                    dated_position_side=action.dated_position_side,
                    position_date=action.position_date,
                    offset_flag=action.offset_flag,
                    hedge_flag=action.hedge_flag,
                    query_set_id=action.dated_query_set_id,
                    snapshot_id=action.dated_snapshot_id,
                    account_fingerprint=action.dated_account_fingerprint,
                    connection_generation=action.dated_connection_generation,
                    trading_day=action.dated_trading_day,
                    available_at=(
                        _time_key(action.dated_available_at)
                        if action.dated_available_at is not None
                        else None
                    ),
                    source_row_ids=action.dated_source_row_ids,
                    opening_execution_ids=action.dated_opening_execution_ids,
                    close_execution_ids=action.dated_close_execution_ids,
                )
            if action.position_effect == "OPEN":
                if action.action == "CANCEL":
                    economic.update(
                        owner_intent_id=action.owner_intent_id,
                        order_ref=action.order_ref,
                    )
                elif self._risk_policy is None or action.planned_stop_price is None:
                    raise ValueError("OPEN intent is missing explicit stop/risk policy economics")
                else:
                    economic.update(
                        factor_stop_price=str(action.planned_stop_price),
                        stop_price=str(action.planned_stop_price),
                        risk_policy_id=self._risk_policy.risk_policy_id,
                        risk_policy=self._risk_policy_payload(),
                        entry_grid_ordinal=action.entry_grid_ordinal,
                    )
            elif action.position_effect == "CLOSE":
                economic["owner_intent_id"] = action.owner_intent_id
                economic["owner_side"] = "BUY" if action.side == "SELL" else "SELL"
                economic["owner_position_effect"] = "OPEN"
                economic["dated_position_side"] = action.dated_position_side
                economic["position_date"] = action.position_date
                economic["offset_flag"] = action.offset_flag
                economic["hedge_flag"] = action.hedge_flag
            elif action.action == "CANCEL":
                economic["owner_intent_id"] = action.owner_intent_id
                economic["order_ref"] = action.order_ref
            economics.append(MappingProxyType(economic))
        return tuple(keys), tuple(economics)

    def _risk_policy_payload(self) -> Mapping[str, Any]:
        if self._risk_policy is None:
            return MappingProxyType({})
        payload = {}
        for name in Alpha003RiskPolicy.__dataclass_fields__:
            value = getattr(self._risk_policy, name)
            payload[name] = str(value) if isinstance(value, Decimal) else value
        return MappingProxyType(payload)

    def _record_decision_tape(
        self,
        batch: Any,
        snapshot: Any,
        target_decision: Optional[Alpha003TargetDecision],
        order_plan: Alpha003OrderPlan,
    ) -> Tuple[bool, Optional[Mapping[str, Any]], Optional[str]]:
        """Durably append public market/factor evidence before any order dispatch."""

        batch_id = _read(batch, "batch_id") if batch is not None else None
        if not isinstance(batch_id, str) or not batch_id:
            return False, None, "DECISION_TAPE_BATCH_UNAVAILABLE"
        if self._last_decision_tape_batch_id == batch_id:
            reference = self._last_decision_tape_reference
            return (reference is not None), reference, self._last_decision_tape_error

        # Mark the attempt first. An exception after fsync has an unknown
        # outcome; retrying could append duplicate evidence for this grid.
        self._last_decision_tape_batch_id = batch_id
        self._last_decision_tape_reference = None
        self._last_decision_tape_error = "DECISION_TAPE_UNAVAILABLE"
        sink = self.p.decision_tape
        writer = getattr(sink, "record_decision", None) if sink is not None else None
        if not callable(writer):
            return False, None, self._last_decision_tape_error
        try:
            result = writer(batch, snapshot, target_decision, order_plan)
            if type(result) is not bool or result is not True:
                self._last_decision_tape_error = "DECISION_TAPE_WRITE_NOT_CONFIRMED"
                return False, None, self._last_decision_tape_error
            file_id = getattr(sink, "file_id", None)
            raw_reference = getattr(sink, "last_record_reference", None)
            if not isinstance(file_id, str) or not file_id:
                self._last_decision_tape_error = "DECISION_TAPE_REFERENCE_INVALID"
                return False, None, self._last_decision_tape_error
            if not isinstance(raw_reference, Mapping):
                self._last_decision_tape_error = "DECISION_TAPE_REFERENCE_INVALID"
                return False, None, self._last_decision_tape_error
            reference = {
                "file_id": raw_reference.get("file_id"),
                "record_id": raw_reference.get("record_id"),
                "record_index": raw_reference.get("record_index"),
                "batch_id": raw_reference.get("batch_id"),
            }
            if (
                reference["file_id"] != file_id
                or not isinstance(reference["record_id"], str)
                or not reference["record_id"]
                or type(reference["record_index"]) is not int
                or reference["record_index"] < 1
                or reference["batch_id"] != batch_id
            ):
                self._last_decision_tape_error = "DECISION_TAPE_REFERENCE_INVALID"
                return False, None, self._last_decision_tape_error
        except Exception:
            # Do not put exception text in strategy state or durable payloads.
            self._last_decision_tape_error = "DECISION_TAPE_WRITE_FAILED"
            return False, None, self._last_decision_tape_error

        frozen_reference = MappingProxyType(reference)
        self._last_decision_tape_reference = frozen_reference
        self._last_decision_tape_error = None
        return True, frozen_reference, None

    @staticmethod
    def _gate_open_actions(plan: Alpha003OrderPlan, *, tape_durable: bool) -> Alpha003OrderPlan:
        if tape_durable or plan.status != "READY":
            return plan
        actions = tuple(
            action
            for action in plan.actions
            if action.action == "CANCEL"
            or action.action != "SUBMIT"
            or action.position_effect != "OPEN"
        )
        if actions:
            return replace(plan, reason="OPEN_SUPPRESSED_DECISION_TAPE", actions=actions)
        if any(
            action.action == "SUBMIT" and action.position_effect == "OPEN"
            for action in plan.actions
        ):
            return replace(plan, status="BLOCKED", reason="DECISION_TAPE_NOT_DURABLE", actions=())
        return plan

    def _source_receipt(self, batch: Any, snapshot: Any, tape_reference: Any) -> Any:
        """Bind one sealed batch to its exact fsynced tape row."""

        if not isinstance(tape_reference, Mapping):
            raise ValueError("source receipt requires a durable tape reference")
        reference = {
            name: tape_reference.get(name)
            for name in ("file_id", "record_id", "record_index", "batch_id")
        }
        batch_id = _read(batch, "batch_id")
        if (
            type(reference["file_id"]) is not str
            or not reference["file_id"]
            or type(reference["record_id"]) is not str
            or not reference["record_id"]
            or type(reference["record_index"]) is not int
            or reference["record_index"] < 1
            or reference["batch_id"] != batch_id
        ):
            raise ValueError("source receipt tape reference is invalid")
        if self._source_receipt_batch_id == batch_id:
            if dict(self._source_receipt_tape_reference or {}) != reference:
                raise ValueError("source receipt tape reference changed for one batch")
            if self._source_receipt_cache is None:
                raise ValueError("source receipt cache is unavailable")
            return self._source_receipt_cache

        from backtrader.stores.execution_decision_journal import (
            ExecutionSourceMemberReceipt,
            ExecutionSourceReceipt,
        )

        members = _read(batch, "members")
        if (
            not isinstance(members, Mapping)
            or not members
            or tuple(sorted(members)) != tuple(sorted(self._target_ids))
        ):
            raise ValueError("source receipt member batch is unavailable")
        member_receipts = []
        for member_id in sorted(members):
            delivered = members[member_id]
            envelope = _read(delivered, "envelope")
            member_receipts.append(
                ExecutionSourceMemberReceipt(
                    member_id=member_id,
                    source_ref=_read(envelope, "source_ref"),
                    source_role=_read(envelope, "source_role"),
                    connection_generation=_read(envelope, "connection_generation"),
                    feed_sequence=_read(envelope, "feed_sequence"),
                    bar_id=_read(envelope, "bar_id"),
                    bucket_start=_time_key(_read(envelope, "bucket_start")),
                    close_time=_time_key(_read(envelope, "close_time")),
                    available_at=_time_key(_read(envelope, "available_at")),
                    trading_day=_canonical_source_trading_day(
                        _read(envelope, "trading_day")
                    ),
                    session_segment=_read(envelope, "session_segment"),
                    timezone_id=_read(envelope, "timezone_id"),
                    clock_domain_id=_read(envelope, "clock_domain_id"),
                    complete=_read(envelope, "complete"),
                    quality=_read(envelope, "quality"),
                    present=_read(envelope, "present"),
                    missing_fields=tuple(_read(envelope, "missing_fields")),
                    quality_flags=tuple(_read(envelope, "quality_flags")),
                    event_source=_read(envelope, "event_source"),
                    received_monotonic_ns=_read(envelope, "received_monotonic_ns"),
                    rules_hash=_read(envelope, "rules_hash"),
                    origin_partition=_read(envelope, "origin_partition"),
                )
            )
        cohort = self.p.cohort
        receipt = ExecutionSourceReceipt(
            source_kind=self._source_kind,
            cohort_id=_read(batch, "cohort_id"),
            calendar_id=_read(batch, "calendar_id"),
            calendar_version=_read(batch, "calendar_version"),
            calendar_fingerprint=_read(cohort, "calendar_fingerprint"),
            epoch_id=_read(batch, "epoch_id"),
            slot_index=_read(batch, "slot_index"),
            slot_id=_read(members[sorted(members)[0]].envelope, "slot_id"),
            close_time=_time_key(_read(batch, "close_time")),
            batch_id=batch_id,
            readiness=_state_name(_read(snapshot, "readiness"), "snapshot readiness"),
            tape_file_id=reference["file_id"],
            tape_record_id=reference["record_id"],
            tape_record_index=reference["record_index"],
            members=tuple(member_receipts),
            predecessor=self._source_predecessor,
            restart_marker=self._source_restart_marker,
        )
        self._source_receipt_batch_id = batch_id
        self._source_receipt_tape_reference = MappingProxyType(reference)
        self._source_receipt_cache = receipt
        return receipt

    def _note_source_continuity_failure(self, code: str) -> None:
        if code not in _SOURCE_CONTINUITY_FAILURE_CODES:
            code = "SOURCE_RECEIPT_WRITE_FAILED"
        self.source_continuity_failure_count += 1
        if self.source_continuity_first_error is None:
            self.source_continuity_first_error = code

    def _confirm_source_anchor(self, receipt: Any, *, anchor_kind: str) -> bool:
        try:
            highwater = self._coordinator.journal.source_highwater(
                self._account_scope,
                self._strategy_scope,
                self._logical_run_id,
                self._source_kind,
            )
            confirmed = bool(
                highwater is not None
                and highwater.receipt == receipt
                and highwater.anchor_kind == anchor_kind
            )
        except Exception:
            confirmed = False
        if not confirmed:
            self._note_source_continuity_failure("SOURCE_HIGHWATER_CONFIRMATION_FAILED")
            return False
        self._source_predecessor = highwater.reference
        self._source_restart_marker = None
        return True

    def _latch_decision_tape_failure(self) -> None:
        sink = getattr(self.p, "decision_tape", None)
        latch = getattr(sink, "latch_failure", None) if sink is not None else None
        if callable(latch):
            try:
                latch()
            except Exception:
                pass

    def _record_source_only(self, batch: Any, snapshot: Any, tape_reference: Any) -> bool:
        """Persist source continuity without entering an order-dispatch scope."""

        if self._coordinator is None:
            self.last_execution_block_reason = "DURABLE_DECISION_COORDINATOR_UNAVAILABLE"
            self._note_source_continuity_failure(
                "DURABLE_DECISION_COORDINATOR_UNAVAILABLE"
            )
            return False
        try:
            from backtrader.stores.execution_decision_journal import ExecutionDecisionKey

            receipt = self._source_receipt(batch, snapshot, tape_reference)
            key = ExecutionDecisionKey(
                account_scope=self._account_scope,
                strategy_scope=self._strategy_scope,
                logical_run_id=self._logical_run_id,
                cohort_id=receipt.cohort_id,
                close_time=receipt.close_time,
                decision_kind=self._source_kind,
            )
            if receipt.readiness in ("WARMUP", "CATCHING_UP"):
                sink = self.p.decision_tape
                verified_prewarm = (
                    getattr(sink, "record_verified_source_prewarm", None)
                    if sink is not None
                    else None
                )
                if not callable(verified_prewarm):
                    raise ValueError("verified source tape writer is unavailable")
                verified_prewarm(
                    key=key,
                    batch=batch,
                    source_receipt=receipt,
                    coordinator=self._coordinator,
                )
            else:
                self._coordinator.record_source_receipt(
                    key=key,
                    batch=batch,
                    source_receipt=receipt,
                )
            if not self._confirm_source_anchor(receipt, anchor_kind="SOURCE_ONLY"):
                self._latch_decision_tape_failure()
                return False
            return True
        except Exception:
            self._latch_decision_tape_failure()
            self.last_execution_block_reason = "SOURCE_RECEIPT_WRITE_FAILED"
            self._note_source_continuity_failure("SOURCE_RECEIPT_WRITE_FAILED")
            return False

    @staticmethod
    def _live_good_source_batch(batch: Any, snapshot: Any) -> bool:
        try:
            readiness = _state_name(_read(snapshot, "readiness"), "snapshot readiness")
            members = _read(batch, "members")
            return bool(
                readiness == "LIVE_READY"
                and isinstance(members, Mapping)
                and members
                and all(
                    _read(_read(member, "envelope"), "source_role") == "live"
                    and _read(_read(member, "envelope"), "complete") is True
                    and _read(_read(member, "envelope"), "quality") == "GOOD"
                    and _read(_read(member, "envelope"), "present") is True
                    and not _read(_read(member, "envelope"), "missing_fields")
                    and set(
                        _read(_read(member, "envelope"), "quality_flags")
                    ).issubset({"LEGACY_SCHEMA"})
                    for member in members.values()
                )
            )
        except Exception:
            return False

    @staticmethod
    def _no_intent_source_tape_plan(batch: Any, snapshot: Any) -> Alpha003OrderPlan:
        readiness = _state_name(_read(snapshot, "readiness"), "snapshot readiness")
        reason = {
            "WARMUP": "CALCULATION_WARMUP",
            "CATCHING_UP": "SOURCE_CATCHING_UP",
        }.get(readiness, "SOURCE_NOT_LIVE_READY")
        return Alpha003OrderPlan(
            "NO_ACTION",
            reason,
            (),
            _read(batch, "batch_id"),
            _read(batch, "available_at"),
            None,
        )

    def _live_grid_decision(
        self,
        batch: Any,
        snapshot: Any,
        facts: Any,
        plan: Alpha003OrderPlan,
        *,
        planning: Optional[Alpha003OrderPlanningInput] = None,
        decision_tape_reference: Optional[Mapping[str, Any]] = None,
        tape_error: Optional[str] = None,
        source_receipt: Any = None,
        proposed_plan: Optional[Alpha003OrderPlan] = None,
        loss_guard_context: Any = None,
        loss_guard_blocker: Optional[str] = None,
    ) -> bool:
        self._last_grid_fee_pair_blocked = False
        if (
            batch is None
            or snapshot is None
            or _state_name(_read(snapshot, "readiness"), "snapshot readiness") != "LIVE_READY"
            or _read(snapshot, "batch_complete") is not True
        ):
            return False
        if self._coordinator is None:
            self.last_execution_block_reason = "DURABLE_DECISION_COORDINATOR_UNAVAILABLE"
            return False
        if proposed_plan is None:
            proposed_plan = plan
        proposed_actions = tuple(proposed_plan.actions) if proposed_plan.status == "READY" else ()
        grid_actions = (
            tuple(
                action
                for action in plan.actions
                if action.action == "SUBMIT" and action.position_effect == "OPEN"
            )
            if self.p.execution_enabled
            else ()
        )
        grid_plan = replace(plan, actions=grid_actions)
        keys, economics = self._order_intents(grid_plan, batch) if grid_actions else ((), ())
        from backtrader.stores.execution_decision_journal import ExecutionDecisionKey

        key = ExecutionDecisionKey(
            account_scope=self._account_scope,
            strategy_scope=self._strategy_scope,
            logical_run_id=self._logical_run_id,
            cohort_id=_read(batch, "cohort_id"),
            close_time=_time_key(_read(batch, "close_time")),
            decision_kind=self._source_kind,
        )
        economic_payload = {
            "plan_id": FACTOR_NAME,
            "factor_source_sha256": _read(_read(snapshot, "factors")[FACTOR_NAME], "source_sha256"),
            "snapshot_id": getattr(facts, "snapshot_id", None),
            "execution_evidence": _live_execution_evidence_payload(facts),
            "batch_id": _read(batch, "batch_id"),
            "epoch_id": _read(batch, "epoch_id"),
            "signal_batch_id": (
                self._last_signal_target.batch_id if self._last_signal_target is not None else None
            ),
            "decision_tape_status": "DURABLE" if decision_tape_reference is not None else "FAILED",
            "decision_tape_error": tape_error,
            "intent_economics": economics,
            "proposed_actions": tuple(
                _planned_action_payload(action) for action in proposed_actions
            ),
            "dispatch_suppressed": not self.p.execution_enabled or tape_error is not None,
            "plan_status": plan.status,
            "plan_reason": plan.reason,
        }
        risk_candidate_payload = _open_risk_candidate_payload(
            proposed_plan.open_risk_candidate
        )
        if risk_candidate_payload is not None:
            economic_payload["open_risk_candidate"] = risk_candidate_payload
        if decision_tape_reference is not None:
            for name in ("file_id", "record_id", "record_index", "batch_id"):
                economic_payload["decision_tape_" + name] = decision_tape_reference[name]
        current_batch = self.p.cohort.current_batch()
        current_snapshot = self.live_factors.snapshot()
        if (
            current_batch is not batch
            or current_snapshot != snapshot
            or _state_name(_read(current_snapshot, "readiness"), "snapshot readiness")
            != "LIVE_READY"
            or _read(current_snapshot, "batch_complete") is not True
            or _read(current_snapshot, "batch_id") != _read(batch, "batch_id")
            or _read(current_snapshot, "cohort_id") != _read(batch, "cohort_id")
            or _read(current_snapshot, "calendar_id") != _read(batch, "calendar_id")
            or _read(current_snapshot, "epoch_id") != _read(batch, "epoch_id")
            or _read(current_snapshot, "close_time") != _read(batch, "close_time")
        ):
            self.last_execution_block_reason = "FACTOR_SNAPSHOT_CHANGED_BEFORE_DECISION"
            return False
        from backtrader.stores.execution_decision_journal import ExecutionDecisionJournalError
        from backtrader.stores.factor_execution import FactorExecutionError

        try:
            if (
                self.p.execution_enabled
                and self._coordinator.journal.fee_pair_required_scope(
                    self._account_scope, self._strategy_scope
                )
                is not None
            ):
                # A registered scope cannot advance any ordinary grid, even
                # when an earlier guard would otherwise stop before the write.
                # The read verifies the immutable fence; the journal's write
                # transaction remains the authority for concurrent registration.
                raise ExecutionDecisionJournalError("FEE_PAIR_SCOPE_FAIL_CLOSED")
            if self.p.execution_enabled and grid_actions and loss_guard_context is None:
                # A prior row must get its canonical payload/economics check
                # before any mutable guard state can affect exact replay.
                # A new OPEN cannot proceed without a source-bound context.
                if self._coordinator.journal.decision_for_key(key) is None:
                    raise FactorExecutionError(
                        loss_guard_blocker or "RUN_LOSS_GUARD_CONTEXT_REQUIRED"
                    )
            with self._coordinator.decision_scope(
                owner=self,
                key=key,
                economic_payload=economic_payload,
                intent_keys=keys,
                batch=batch,
                snapshot=current_snapshot,
                execution_facts=facts,
                inputs_complete=True,
                expected_run_order_intents_used=(
                    planning.run_order_intents_used
                    if planning is not None
                    else self._coordinator.run_order_count()
                ),
                remaining_exit_intent_reserve=(
                    _future_exit_intent_reserve(
                        planning,
                        planned_actions=grid_actions,
                        proposed_open_actions=grid_actions,
                    )
                    if planning is not None
                    else 0
                ),
                loss_guard_context=loss_guard_context,
                source_receipt=source_receipt,
            ) as scope:
                if self.p.execution_enabled and scope.dispatch_allowed and grid_actions:
                    self._dispatch_live_actions(grid_actions, batch)
            if source_receipt is not None:
                if not self._confirm_source_anchor(source_receipt, anchor_kind="GRID"):
                    # The GRID transaction may already have authorized/recorded
                    # its decision. Do not retry this key as SOURCE_ONLY.
                    return True
        except (FactorExecutionError, ExecutionDecisionJournalError) as error:
            code = getattr(error, "code", None)
            if code == "FEE_PAIR_SCOPE_FAIL_CLOSED":
                # The registered scope has no source/grid settlement yet.
                # Suppress every new OPEN, but keep independently planned
                # risk reductions for the later ALPHA003_RISK_REDUCTION path.
                self.last_execution_block_reason = code
                reductions = tuple(
                    action
                    for action in plan.actions
                    if action.action == "CANCEL"
                    or (action.action == "SUBMIT" and action.position_effect == "CLOSE")
                )
                self.last_order_plan = replace(
                    plan,
                    status="READY" if reductions else "BLOCKED",
                    reason=code,
                    actions=reductions,
                )
                self._last_grid_fee_pair_blocked = True
                return False
            if type(code) is not str or code not in _RUN_LOSS_OPEN_REJECTION_CODES:
                raise
            self.last_execution_block_reason = code
            open_actions = tuple(
                action
                for action in plan.actions
                if action.action == "SUBMIT" and action.position_effect == "OPEN"
            )
            if open_actions:
                reductions = tuple(
                    action
                    for action in plan.actions
                    if action.action == "CANCEL"
                    or (action.action == "SUBMIT" and action.position_effect == "CLOSE")
                )
                self.last_order_plan = replace(
                    plan,
                    status="READY" if reductions else "BLOCKED",
                    reason=code,
                    actions=reductions,
                )
            return False
        return True

    def _confirmed_live_ready_event(
        self, batch: Any, snapshot: Any
    ) -> Optional[dict[str, Any]]:
        if self.p.replay_mode or batch is None or snapshot is None:
            return None
        try:
            batch_id = _read(batch, "batch_id")
            cohort_id = _read(batch, "cohort_id")
            epoch_id = _read(batch, "epoch_id")
            calendar_id = _read(batch, "calendar_id")
            slot_index = _read(batch, "slot_index")
            members = _read(batch, "members")
            target_ids = getattr(self, "_target_ids", None)
            if (
                _read(batch, "status") != "COMPLETE"
                or _state_name(_read(snapshot, "readiness"), "snapshot readiness")
                != "LIVE_READY"
                or _read(snapshot, "batch_complete") is not True
                or _read(snapshot, "batch_id") != batch_id
                or _read(snapshot, "cohort_id") != cohort_id
                or _read(snapshot, "epoch_id") != epoch_id
                or _read(snapshot, "calendar_id") != _read(batch, "calendar_id")
                or _read(snapshot, "close_time") != _read(batch, "close_time")
                or _read(snapshot, "available_at") != _read(batch, "available_at")
                or not isinstance(members, Mapping)
                or not members
                or type(target_ids) is not tuple
                or not target_ids
                or any(type(target_id) is not str or not target_id for target_id in target_ids)
                or len(set(target_ids)) != len(target_ids)
                or set(members) != set(target_ids)
                or not all(
                    _read(_read(receipt, "envelope"), "source_role") == "live"
                    and _read(_read(receipt, "envelope"), "complete") is True
                    and _read(_read(receipt, "envelope"), "quality") == "GOOD"
                    and _read(_read(receipt, "envelope"), "present") is True
                    and not _read(_read(receipt, "envelope"), "missing_fields")
                    and set(_read(_read(receipt, "envelope"), "quality_flags")).issubset(
                        {"LEGACY_SCHEMA"}
                    )
                    for receipt in members.values()
                )
            ):
                return None
            if (
                self.p.cohort.current_batch() is not batch
                or self.live_factors.snapshot() != snapshot
            ):
                return None
            if (
                type(cohort_id) is not str or not cohort_id
                or type(epoch_id) is not int or epoch_id <= 0
                or type(calendar_id) is not str or not calendar_id
                or type(slot_index) is not int or slot_index < 0
                or type(batch_id) is not str or not batch_id
            ):
                return None
        except Exception:
            return None
        return {
            "readiness": "LIVE_READY",
            "replay_mode": False,
            "cohort_id": cohort_id,
            "epoch_id": epoch_id,
            "calendar_id": calendar_id,
            "batch_id": batch_id,
            "slot_index": slot_index,
        }

    def _capture_live_ready_boundary(self, batch: Any, snapshot: Any) -> None:
        """Notify an optional observer once after the first full live snapshot."""
        callback = getattr(self.p, "live_ready_callback", None)
        if callback is None or self._live_ready_callback_attempted:
            return
        event = self._confirmed_live_ready_event(batch, snapshot)
        if event is None:
            return
        self._live_ready_callback_attempted = True
        try:
            callback(event)
            self._live_ready_event_identity = (
                event["cohort_id"],
                event["epoch_id"],
                event["calendar_id"],
                event["slot_index"],
                event["batch_id"],
            )
            self._live_ready_callback_completed = True
        except Exception:
            # Telemetry failure must not interrupt the engine or resource cleanup.
            self._live_ready_callback_failed = True

    def _capture_live_next_boundary(self, batch: Any, snapshot: Any) -> None:
        """Record entry into regular ``next`` at the ready batch or a later slot."""
        callback = getattr(self.p, "live_next_callback", None)
        if (
            callback is None
            or self.p.replay_mode
            or not self._live_ready_callback_completed
            or self._live_next_callback_attempted
        ):
            return
        event = self._confirmed_live_ready_event(batch, snapshot)
        if event is None or self._live_ready_event_identity is None:
            return
        ready_cohort, ready_epoch, ready_calendar, ready_slot, ready_batch = (
            self._live_ready_event_identity
        )
        if (
            event["cohort_id"] != ready_cohort
            or event["epoch_id"] != ready_epoch
            or event["calendar_id"] != ready_calendar
            or event["slot_index"] < ready_slot
            or (
                event["slot_index"] == ready_slot
                and event["batch_id"] != ready_batch
            )
            or (
                event["slot_index"] > ready_slot
                and event["batch_id"] == ready_batch
            )
        ):
            return
        self._live_next_callback_attempted = True
        try:
            callback(event)
            self._live_next_callback_completed = True
        except Exception:
            # A missing next receipt makes the memory run incomplete; it must not
            # change engine behavior or interfere with the normal cleanup path.
            self._live_next_callback_failed = True

    def _capture_live_capacity_boundary(
        self, batch: Any, snapshot: Any, *, engine_phase: str
    ) -> None:
        """Pass a confirmed live boundary to an opt-in count-only observer."""
        callback = getattr(self.p, "live_capacity_callback", None)
        if callback is None:
            return
        event = self._confirmed_live_ready_event(batch, snapshot)
        if event is None:
            return
        observed = dict(event)
        observed.update(
            {
                "run_id": getattr(self.p, "logical_run_id", None),
                "grid_ordinal": event["slot_index"],
                "engine_phase": engine_phase,
            }
        )
        try:
            callback(self, observed)
            self._live_capacity_callback_count = (
                getattr(self, "_live_capacity_callback_count", 0) + 1
            )
        except Exception:
            # This optional observer must never change orders or normal cleanup.
            self._live_capacity_callback_failed = True

    def _live_risk_decision(
        self,
        batch: Any,
        facts: Any,
        plan: Alpha003OrderPlan,
        *,
        planning: Optional[Alpha003OrderPlanningInput] = None,
    ) -> None:
        if (
            not self.p.execution_enabled
            or self._coordinator is None
            or facts is None
            or plan.status != "READY"
        ):
            return
        actions = tuple(
            action
            for action in plan.actions
            if action.position_effect == "CLOSE" or action.action == "CANCEL"
        )
        if not actions:
            return
        if any(
            action.action == "CANCEL" and self._find_order_object(action) is None
            for action in actions
        ):
            self.last_execution_block_reason = "CANCEL_ORDER_OBJECT_UNAVAILABLE"
            return
        plan_for_risk = replace(plan, actions=actions)
        keys, economics = self._order_intents(plan_for_risk, batch)
        event_time = getattr(facts, "available_at", None)
        if event_time is None:
            self.last_execution_block_reason = "RISK_EVENT_TIME_UNAVAILABLE"
            return
        from backtrader.stores.execution_decision_journal import ExecutionDecisionKey

        key = ExecutionDecisionKey(
            account_scope=self._account_scope,
            strategy_scope=self._strategy_scope,
            logical_run_id=self._logical_run_id,
            cohort_id=_read(self.p.cohort, "cohort_id"),
            close_time=_time_key(event_time),
            decision_kind="ALPHA003_RISK_REDUCTION",
        )
        payload = {
            "snapshot_id": facts.snapshot_id,
            "available_at": _time_key(event_time),
            "execution_evidence": _live_execution_evidence_payload(facts),
            "batch_id": _read(batch, "batch_id") if batch is not None else None,
            "intent_economics": economics,
            "plan_reason": plan.reason,
        }
        with self._coordinator.risk_decision_scope(
            owner=self,
            key=key,
            economic_payload=payload,
            intent_keys=keys,
            # Risk keys use the fact snapshot's event/completion time. That
            # can follow the market batch close when a fresh quote/query was
            # consumed, so do not bind its independent durable key to the
            # batch close timestamp.
            batch=None,
            execution_facts=facts,
            inputs_complete=True,
            expected_run_order_intents_used=(
                planning.run_order_intents_used
                if planning is not None
                else self._coordinator.run_order_count()
            ),
            remaining_exit_intent_reserve=(
                _future_exit_intent_reserve(planning, planned_actions=actions)
                if planning is not None
                else 0
            ),
        ) as scope:
            if scope.dispatch_allowed:
                self._dispatch_live_actions(actions, batch)

    def _run_live_prenext_risk(self) -> None:
        """Evaluate only fresh live risk reductions during factor warmup."""

        if self.p.replay_mode or not self.p.execution_enabled:
            return
        if self._coordinator is None:
            self.last_execution_block_reason = "DURABLE_DECISION_COORDINATOR_UNAVAILABLE"
            return
        try:
            now = self._clock_now()
        except (TypeError, ValueError, RuntimeError):
            self.last_execution_block_reason = "MARKET_DECISION_TIME_UNAVAILABLE"
            return
        facts = self._live_facts(now)
        if facts is None:
            return
        planning = _live_planning_input(
            facts,
            strategy_scope=self._strategy_scope,
            evaluated_at=now,
            risk_evidence_available_at=facts.available_at,
            session_close_at=None,
            run_end=self._shutdown_requested.is_set(),
            risk_policy=self._risk_policy,
            target_decision=None,
            eligible_grid_ordinal=None,
            run_order_intents_used=self._coordinator.run_order_count(),
        )
        self.last_order_plan = plan_alpha003_orders(planning)
        self._live_risk_decision(None, facts, self.last_order_plan, planning=planning)

    def _dispatch_live_actions(self, actions: Tuple[Alpha003OrderAction, ...], batch: Any) -> None:
        for action in actions:
            if action.action == "CANCEL":
                order = self._find_order_object(action)
                if order is None:
                    self.last_execution_block_reason = "CANCEL_ORDER_OBJECT_UNAVAILABLE"
                    return
                self.cancel(order)
                continue
            data = self._data_by_target[action.target_id]
            info = {
                "instrument_id": action.instrument,
                "exchange_id": action.exchange,
                "factor_position_effect": action.position_effect,
                "factor_strategy_scope": self._strategy_scope,
                "offset": action.offset,
            }
            if action.position_side is not None:
                info["position_side"] = action.position_side
            if action.position_effect == "CLOSE":
                info.update(
                    factor_owner_side="BUY" if action.side == "SELL" else "SELL",
                    factor_owner_position_effect="OPEN",
                )
            if action.position_date is not None:
                info.update(
                    hedge_flag=action.hedge_flag,
                    position_date=action.position_date,
                    offset_flag=action.offset_flag,
                    factor_dated_position_side=action.dated_position_side,
                    factor_dated_query_set_id=action.dated_query_set_id,
                    factor_dated_snapshot_id=action.dated_snapshot_id,
                    factor_dated_account_fingerprint=action.dated_account_fingerprint,
                    factor_dated_connection_generation=action.dated_connection_generation,
                    factor_dated_trading_day=action.dated_trading_day,
                    factor_dated_available_at=(
                        _time_key(action.dated_available_at)
                        if action.dated_available_at is not None
                        else None
                    ),
                    factor_dated_source_row_ids=action.dated_source_row_ids,
                    factor_dated_opening_execution_ids=action.dated_opening_execution_ids,
                    factor_dated_close_execution_ids=action.dated_close_execution_ids,
                )
            if action.position_effect == "OPEN":
                info.update(
                    factor_stop_price=str(action.planned_stop_price),
                    factor_entry_grid_ordinal=action.entry_grid_ordinal,
                    factor_risk_policy_id=self._risk_policy.risk_policy_id,
                    factor_risk_policy=self._risk_policy_payload(),
                )
            method = self.buy if action.side == "BUY" else self.sell
            order = method(
                data=data,
                size=action.quantity,
                price=float(action.limit_price) if action.limit_price is not None else None,
                exectype=bt.Order.Limit if action.limit_price is not None else bt.Order.Market,
                **info,
            )
            if order is not None:
                self._orders_by_broker_ref[order.ref] = order

    def _run_live(
        self,
        batch: Any,
        snapshot: Any,
        now: datetime,
        ordinal: Optional[int],
        session_close: Optional[datetime],
        run_end: bool,
        *,
        is_new_batch: bool,
        session_reason: Optional[str] = None,
    ) -> None:
        self._last_grid_fee_pair_blocked = False
        facts = self._live_facts(now)
        loss_guard_context = None
        loss_guard_blocker = None
        if facts is not None and self.p.execution_enabled:
            loss_guard_context, loss_guard_blocker = self._refresh_run_loss_guard(facts, now)
            if loss_guard_blocker is not None:
                self.last_execution_block_reason = loss_guard_blocker
        target_decision = None if run_end else self._last_signal_target
        planning = None
        run_order_intents_used = (
            self._coordinator.run_order_count()
            if self._coordinator is not None
            else self._live_shadow_order_count
        )
        if facts is not None and self._risk_policy is not None:
            planning = _live_planning_input(
                facts,
                strategy_scope=self._strategy_scope,
                evaluated_at=now,
                risk_evidence_available_at=(
                    _read(batch, "available_at") if batch is not None else facts.available_at
                ),
                session_close_at=session_close,
                run_end=run_end,
                risk_policy=self._risk_policy,
                target_decision=target_decision,
                eligible_grid_ordinal=ordinal,
                run_order_intents_used=run_order_intents_used,
            )
            if session_reason is not None:
                planning = replace(
                    planning,
                    execution_blockers=tuple(
                        dict.fromkeys(planning.execution_blockers + (session_reason,))
                    ),
                )
            self.last_order_plan = plan_alpha003_orders(planning)
        else:
            self.last_order_plan = Alpha003OrderPlan(
                "BLOCKED",
                "EXECUTION_FACTS_UNAVAILABLE",
                (),
                _read(batch, "batch_id") if batch is not None else None,
                now,
                None,
            )
        proposed_plan = self.last_order_plan
        tape_order_plan = proposed_plan
        if (
            is_new_batch
            and batch is not None
            and snapshot is not None
            and not self._live_good_source_batch(batch, snapshot)
        ):
            tape_order_plan = self._no_intent_source_tape_plan(batch, snapshot)
        tape_durable = False
        tape_reference = None
        tape_error = None
        if is_new_batch and batch is not None and snapshot is not None:
            tape_durable, tape_reference, tape_error = self._record_decision_tape(
                batch, snapshot, target_decision, tape_order_plan
            )
            if not tape_durable:
                self.last_execution_block_reason = tape_error
            self.last_order_plan = self._gate_open_actions(proposed_plan, tape_durable=tape_durable)
        if is_new_batch and batch is not None and snapshot is not None and tape_durable:
            source_receipt = None
            try:
                source_receipt = self._source_receipt(batch, snapshot, tape_reference)
            except Exception:
                self.last_execution_block_reason = "SOURCE_RECEIPT_BUILD_FAILED"
                self._note_source_continuity_failure("SOURCE_RECEIPT_BUILD_FAILED")
                self.last_order_plan = self._gate_open_actions(
                    proposed_plan, tape_durable=False
                )
            if source_receipt is not None:
                readiness = _state_name(_read(snapshot, "readiness"), "snapshot readiness")
                live_good_batch = (
                    readiness == "LIVE_READY"
                    and source_receipt.readiness == readiness
                    and self._live_good_source_batch(batch, snapshot)
                )
                grid_recorded = False
                if live_good_batch:
                    grid_recorded = self._live_grid_decision(
                        batch,
                        snapshot,
                        facts,
                        self.last_order_plan,
                        decision_tape_reference=tape_reference,
                        tape_error=tape_error,
                        source_receipt=source_receipt,
                        proposed_plan=proposed_plan,
                        planning=planning,
                        loss_guard_context=loss_guard_context,
                        loss_guard_blocker=loss_guard_blocker,
                    )
                    ready_callback = getattr(self.p, "live_ready_callback", None)
                    capture_ready = getattr(self, "_capture_live_ready_boundary", None)
                    if grid_recorded and callable(ready_callback) and callable(capture_ready):
                        # A readiness receipt is an execution boundary: don't
                        # publish it until the source/grid anchor is durable.
                        capture_ready(batch, snapshot)
                    capacity_callback = getattr(self.p, "live_capacity_callback", None)
                    capture_capacity = getattr(self, "_capture_live_capacity_boundary", None)
                    if grid_recorded and callable(capacity_callback) and callable(capture_capacity):
                        capture_capacity(batch, snapshot, engine_phase="grid_recorded")
                if not grid_recorded:
                    if not getattr(self, "_last_grid_fee_pair_blocked", False):
                        self._record_source_only(batch, snapshot, tape_reference)
        elif is_new_batch and batch is not None and snapshot is not None:
            # No tape row means there is no source identity to anchor and no
            # grid decision may advance. Fresh risk reductions still run below.
            self.last_execution_block_reason = tape_error or "SOURCE_TAPE_UNAVAILABLE"
        if self.p.execution_enabled and planning is not None:
            self._live_risk_decision(batch, facts, self.last_order_plan, planning=planning)
        if self._shutdown_requested.is_set():
            self._update_shutdown_state(facts, self.last_order_plan)

    def _run_replay(
        self,
        batch: Any,
        snapshot: Any,
        now: datetime,
        ordinal: Optional[int],
        session_close: Optional[datetime],
        run_end: bool,
        *,
        session_reason: Optional[str] = None,
    ) -> None:
        if batch is None:
            self.last_order_plan = Alpha003OrderPlan(
                "BLOCKED", "NO_COMPLETE_BATCH", (), None, now, None
            )
            return
        floor = self.broker.current_decision_floor()
        risk_cutoff = max(
            floor,
            _as_utc(_read(batch, "available_at"), "batch available_at"),
            _as_utc(_read(snapshot, "available_at"), "snapshot available_at"),
        )
        planning = self._replay_planning_input(
            batch=batch,
            now=now,
            risk_evidence_at=risk_cutoff,
            session_close_at=session_close,
            run_end=run_end,
            ordinal=ordinal,
            target_decision=None if run_end else self._last_signal_target,
        )
        if session_reason is not None:
            planning = replace(
                planning,
                execution_blockers=tuple(
                    dict.fromkeys(planning.execution_blockers + (session_reason,))
                ),
            )
        if ordinal is not None:
            self._update_replay_holding_age(ordinal)
            planning = replace(
                planning,
                positions=tuple(
                    replace(
                        position,
                        held_eligible_bars=(
                            self._replay_owners[position.target_id].get("held_eligible_bars")
                            if position.target_id in self._replay_owners and position.quantity
                            else position.held_eligible_bars
                        ),
                    )
                    for position in planning.positions
                ),
            )
        self.last_order_plan = plan_alpha003_orders(planning)
        proposed_plan = self.last_order_plan
        tape_durable, tape_reference, tape_error = self._record_decision_tape(
            batch, snapshot, self._last_signal_target, proposed_plan
        )
        if not tape_durable:
            self.last_execution_block_reason = tape_error
        self.last_order_plan = self._gate_open_actions(proposed_plan, tape_durable=tape_durable)
        if self.p.execution_enabled:
            self._dispatch_replay_actions(self.last_order_plan, batch)
        if self._shutdown_requested.is_set():
            self._update_replay_shutdown_state()

    def request_shutdown(self) -> None:
        """Request graceful winddown; order decisions stay on the engine thread."""

        self._shutdown_requested.set()
        self._shutdown_post_join_confirmed_state = False
        self._shutdown_post_join_blocker_state = "SHUTDOWN_POST_JOIN_CONFIRMATION_PENDING"
        if not self._shutdown_ready_state:
            self._shutdown_blocker_state = "SHUTDOWN_REQUESTED_PENDING_ENGINE"

    @property
    def shutdown_requested(self) -> bool:
        return self._shutdown_requested.is_set()

    @property
    def shutdown_ready(self) -> bool:
        """Whether this Strategy's target-scope winddown is authoritatively clear."""

        return bool(self._shutdown_ready_state)

    @property
    def shutdown_blocker(self) -> Optional[str]:
        return self._shutdown_blocker_state

    @property
    def shutdown_post_join_confirmed(self) -> bool:
        """Whether a fresh owner-scope check passed after refresh stopped."""

        return self._shutdown_post_join_confirmed_state is True

    @property
    def shutdown_post_join_blocker(self) -> Optional[str]:
        """Reason final post-join retirement evidence was unavailable or blocked."""

        return self._shutdown_post_join_blocker_state

    def _passive_read_only_retirement_proven(self, facts: Any) -> bool:
        """Require this exact Strategy/Broker/Store session to remain read-only."""

        if (
            getattr(getattr(self, "p", None), "execution_enabled", None) is not False
            or facts is not getattr(self, "last_execution_facts", None)
        ):
            return False
        broker = getattr(self, "broker", None)
        store = getattr(broker, "store", None)
        if (
            broker is not getattr(self, "_last_execution_facts_broker", None)
            or store is None
            or store is not getattr(self, "_last_execution_facts_store", None)
            or getattr(store, "allow_writes", None) is not False
        ):
            return False
        get_param = getattr(broker, "get_param", None)
        audit_reader = getattr(broker, "get_market_data_only_audit", None)
        if not callable(get_param) or not callable(audit_reader):
            return False
        try:
            market_data_only = get_param("market_data_only")
            audit = audit_reader()
        except Exception:
            return False
        if type(market_data_only) is not bool or market_data_only is not True:
            return False
        if not isinstance(audit, Mapping):
            return False
        rejected = tuple(
            audit.get(name)
            for name in ("submit_rejected", "cancel_rejected", "batch_cancel_rejected")
        )
        total = audit.get("total_rejected")
        return (
            all(type(count) is int and count == 0 for count in rejected)
            and type(total) is int
            and total == 0
        )

    def _update_shutdown_state(self, facts: Any, plan: Optional[Alpha003OrderPlan]) -> None:
        if not self._shutdown_requested.is_set():
            self._shutdown_ready_state = False
            self._shutdown_blocker_state = "SHUTDOWN_NOT_REQUESTED"
            return
        if facts is None:
            self._shutdown_ready_state = False
            self._shutdown_blocker_state = "SHUTDOWN_FACTS_UNAVAILABLE"
            return
        try:
            from backtrader.stores.factor_execution_facts import FactorExecutionFacts
        except ImportError:
            self._shutdown_ready_state = False
            self._shutdown_blocker_state = "SHUTDOWN_FACT_TYPE_UNAVAILABLE"
            return
        if type(facts) is not FactorExecutionFacts:
            self._shutdown_ready_state = False
            self._shutdown_blocker_state = "SHUTDOWN_FACT_TYPE_INVALID"
            return
        if (
            getattr(facts, "account_scope", None) != self._account_scope
            or getattr(facts, "strategy_scope", None) != self._strategy_scope
        ):
            self._shutdown_ready_state = False
            self._shutdown_blocker_state = "SHUTDOWN_FACT_SCOPE_MISMATCH"
            return
        passive_read_only = self._passive_read_only_retirement_proven(facts)
        if passive_read_only:
            blockers = facts.read_only_observation_blockers
            facts_ready = not blockers
        else:
            facts_ready = facts.read_only_reconciliation_ready is True
            blockers = () if facts_ready else facts.read_only_reconciliation_blockers
        if not facts_ready:
            self._shutdown_ready_state = False
            self._shutdown_blocker_state = (
                "SHUTDOWN_RECONCILIATION_BLOCKED:" + blockers[0]
                if blockers
                else "SHUTDOWN_RECONCILIATION_UNAVAILABLE"
            )
            return
        if passive_read_only:
            positions = tuple(getattr(facts, "positions", ()))
            target_positions = tuple(
                item for item in positions if getattr(item, "target_id", None) is not None
            )
            by_target = {item.target_id: item for item in target_positions}
            if len(by_target) != len(target_positions) or set(by_target) != set(self._target_ids):
                self._shutdown_ready_state = False
                self._shutdown_blocker_state = "SHUTDOWN_POSITION_SET_INCOMPLETE"
                return
            self._shutdown_ready_state = True
            self._shutdown_blocker_state = None
            self._last_shutdown_facts_id = getattr(facts, "snapshot_id", None)
            return

        # Retirement is a read-only reconciliation decision. The planner may
        # be blocked for missing quote, margin, or write-grant evidence even
        # when this complete snapshot proves every target flat and order-free.
        positions = tuple(getattr(facts, "positions", ()))
        by_target = {getattr(item, "target_id", None): item for item in positions}
        if set(by_target) != set(self._target_ids):
            self._shutdown_ready_state = False
            self._shutdown_blocker_state = "SHUTDOWN_POSITION_SET_INCOMPLETE"
            return
        for target_id, position in by_target.items():
            quantity = _exact_hands(getattr(position, "quantity", None))
            if quantity is None:
                self._shutdown_ready_state = False
                self._shutdown_blocker_state = "SHUTDOWN_POSITION_QUANTITY_UNAVAILABLE"
                return
            if quantity:
                if getattr(
                    position, "owner_strategy_scope", None
                ) != self._strategy_scope or not getattr(position, "owner_intent_id", None):
                    self._shutdown_ready_state = False
                    self._shutdown_blocker_state = "SHUTDOWN_POSITION_OWNERSHIP_UNAVAILABLE"
                    return
                if self._risk_policy is None or self._risk_policy.run_end_policy == "CLOSE_ALL":
                    self._shutdown_ready_state = False
                    self._shutdown_blocker_state = "SHUTDOWN_OWNED_POSITION_OPEN:" + target_id
                    return

        target_routes = set(self._routes.values())
        for order in tuple(getattr(facts, "working_orders", ())):
            route = (getattr(order, "instrument", None), getattr(order, "exchange", None))
            if route not in target_routes:
                continue
            if getattr(order, "owner_strategy_scope", None) != self._strategy_scope or not getattr(
                order, "owner_intent_id", None
            ):
                self._shutdown_ready_state = False
                self._shutdown_blocker_state = "SHUTDOWN_WORKING_ORDER_OWNERSHIP_UNAVAILABLE"
                return
            self._shutdown_ready_state = False
            self._shutdown_blocker_state = (
                "SHUTDOWN_ORDER_UNKNOWN"
                if getattr(order, "execution_unknown", False)
                or str(getattr(order, "state", "")).upper()
                in {"UNKNOWN", "DISPATCHING", "PREPARED", "CANCEL_PENDING"}
                else "SHUTDOWN_ORDER_TERMINAL_PENDING"
            )
            return

        self._shutdown_ready_state = True
        self._shutdown_blocker_state = None
        self._last_shutdown_facts_id = getattr(facts, "snapshot_id", None)

    def _request_engine_stop_if_ready(self) -> bool:
        """Request public Cerebro stop only after fresh owner-scope readiness."""

        if not self._shutdown_requested.is_set() or not self._shutdown_ready_state:
            return False
        if self._shutdown_engine_stop_requested:
            return True
        engine = getattr(self, "cerebro", None)
        runstop = getattr(engine, "runstop", None)
        if not callable(runstop):
            self._shutdown_ready_state = False
            self._shutdown_blocker_state = "SHUTDOWN_ENGINE_STOP_UNAVAILABLE"
            return False
        try:
            runstop()
        except Exception:
            self._shutdown_ready_state = False
            self._shutdown_blocker_state = "SHUTDOWN_ENGINE_STOP_FAILED"
            return False
        self._shutdown_engine_stop_requested = True
        return True

    def notify_idle(self) -> None:
        """Consume refresh notices and shutdown requests during market gaps."""

        refresh_loop = getattr(self.p, "control_refresh_loop", None)
        consume_fee_notice = getattr(refresh_loop, "consume_commission_idle_notice", None)
        if callable(consume_fee_notice):
            try:
                notice = consume_fee_notice()
            except Exception:
                notice = None
                self.last_execution_block_reason = "COMMISSION_IDLE_NOTICE_UNAVAILABLE"
            if notice is not None:
                valid_mapping = isinstance(notice, Mapping)
                revision = notice.get("revision") if valid_mapping else None
                priority_changed = notice.get("priority_changed") if valid_mapping else None
                fee_snapshot_changed = notice.get("fee_snapshot_changed") if valid_mapping else None
                batch_id = notice.get("batch_id") if valid_mapping else None
                previous_revision = (
                    self._last_commission_idle_notice.get("revision", 0)
                    if isinstance(self._last_commission_idle_notice, Mapping)
                    else 0
                )
                if (
                    type(revision) is not int
                    or revision <= previous_revision
                    or type(priority_changed) is not bool
                    or type(fee_snapshot_changed) is not bool
                    or (batch_id is not None and (type(batch_id) is not str or not batch_id))
                ):
                    self.last_execution_block_reason = "COMMISSION_IDLE_NOTICE_INVALID"
                else:
                    self._last_commission_idle_notice = MappingProxyType(
                        {
                            "revision": revision,
                            "priority_changed": priority_changed,
                            "fee_snapshot_changed": fee_snapshot_changed,
                            "batch_id": batch_id,
                        }
                    )
                    if (
                        fee_snapshot_changed
                        and not self._shutdown_requested.is_set()
                        and not self.p.replay_mode
                    ):
                        try:
                            self._live_facts(self._clock_now())
                        except Exception:
                            self.last_execution_block_reason = "COMMISSION_IDLE_FACT_REFRESH_FAILED"

        if not self._shutdown_requested.is_set():
            return
        if self.p.replay_mode:
            self._update_replay_shutdown_state()
            self._request_engine_stop_if_ready()
            return
        try:
            now = self._clock_now()
        except (TypeError, ValueError, RuntimeError):
            self._shutdown_ready_state = False
            self._shutdown_blocker_state = "SHUTDOWN_CLOCK_UNAVAILABLE"
            return
        self._run_live(
            None,
            None,
            now,
            None,
            getattr(self, "_last_session_close_at", None),
            True,
            is_new_batch=False,
        )
        self._request_engine_stop_if_ready()

    def prenext(self) -> None:
        """Persist warmup tape rows and maintain only fresh live risk.

        Cerebro calls ``prenext`` while the ordinary factor graph is still
        warming up. Those sealed source rows and their unavailable/partial
        factor outputs are still part of the causal tape, so they are recorded
        before the first ``next`` callback. Live mode then checks existing
        risk reductions from fresh execution facts only; it does not select a
        target or create a grid decision. Replay warmup remains tape-only. A
        calculation-ready grid is left to ``next`` so its target decision and
        any orders share the same tape record.
        """

        try:
            batch, snapshot = self._current_batch_snapshot()
        except (TypeError, ValueError, RuntimeError):
            self.last_execution_block_reason = "PREHEAT_TAPE_BATCH_UNAVAILABLE"
            return
        if batch is None or snapshot is None:
            return
        batch_id = _read(batch, "batch_id")
        if (
            _read(batch, "status") != "COMPLETE"
            or _read(snapshot, "batch_complete") is not True
            or _read(snapshot, "batch_id") != batch_id
            or _read(snapshot, "cohort_id") != _read(batch, "cohort_id")
            or _read(snapshot, "calendar_id") != _read(batch, "calendar_id")
            or _read(snapshot, "epoch_id") != _read(batch, "epoch_id")
            or _read(snapshot, "close_time") != _read(batch, "close_time")
            or _read(snapshot, "available_at") != _read(batch, "available_at")
        ):
            self.last_execution_block_reason = "PREHEAT_TAPE_BATCH_SNAPSHOT_MISMATCH"
            return
        try:
            available_at = _as_utc(_read(snapshot, "available_at"), "snapshot available_at")
            close_time = _as_utc(_read(snapshot, "close_time"), "snapshot close_time")
        except (TypeError, ValueError):
            self.last_execution_block_reason = "PREHEAT_TAPE_TIME_INVALID"
            return
        if available_at < close_time:
            self.last_execution_block_reason = "PREHEAT_TAPE_TIME_INVALID"
            return
        if self.p.replay_mode:
            policy_input = policy_input_from_shared_snapshot(
                batch,
                snapshot,
                required_targets=self._target_ids,
                authorized_targets=self._authorized_targets,
                product_keys=self._product_keys,
                execution_mode="REPLAY",
                eligible_grid_index=max(0, self._eligible_grid_count),
                rebalance_every=self.p.rebalance_every,
            )
            calculation_ready = policy_input.factor.readiness == "REPLAY_READY"
        else:
            calculation_ready = (
                _state_name(_read(snapshot, "readiness"), "snapshot readiness") == "LIVE_READY"
            )
        if calculation_ready:
            if not self.p.replay_mode:
                ready_callback = getattr(self.p, "live_ready_callback", None)
                capture_ready = getattr(self, "_capture_live_ready_boundary", None)
                if callable(ready_callback) and callable(capture_ready):
                    capture_ready(batch, snapshot)
                capacity_callback = getattr(self.p, "live_capacity_callback", None)
                capture_capacity = getattr(self, "_capture_live_capacity_boundary", None)
                if callable(capacity_callback) and callable(capture_capacity):
                    capture_capacity(batch, snapshot, engine_phase="prenext_ready")
            return
        plan = Alpha003OrderPlan(
            "NO_ACTION",
            "CALCULATION_WARMUP",
            (),
            batch_id,
            available_at,
            None,
        )
        durable, _reference, error = self._record_decision_tape(batch, snapshot, None, plan)
        tape_error = error if not durable else None
        source_anchor_error = None
        if tape_error is not None:
            self.last_execution_block_reason = tape_error
        elif not self.p.replay_mode and not self._record_source_only(batch, snapshot, _reference):
            source_anchor_error = "SOURCE_RECEIPT_WRITE_FAILED"
        if not self.p.replay_mode:
            self._run_live_prenext_risk()
        if tape_error is not None:
            self.last_execution_block_reason = tape_error
        elif source_anchor_error is not None:
            self.last_execution_block_reason = source_anchor_error

    def next(self) -> None:
        try:
            batch, snapshot = self._current_batch_snapshot()
            now = self._replay_now() if self.p.replay_mode else self._clock_now()
        except (TypeError, ValueError, RuntimeError):
            self.last_execution_block_reason = "MARKET_DECISION_TIME_UNAVAILABLE"
            return
        is_new = batch is not None and _read(batch, "batch_id") != self._last_batch_id
        ordinal = None
        if batch is not None:
            ordinal = self._update_target_decision(batch, snapshot, is_new=is_new)
            session_close, run_end, session_reason = self._session_facts(batch)
            if session_close is not None:
                self._last_session_close_at = session_close
            if run_end:
                self.request_shutdown()
            run_end = run_end or self._shutdown_requested.is_set()
            if session_reason is not None:
                self.last_execution_block_reason = session_reason
            self._last_batch_id = _read(batch, "batch_id")
        else:
            session_close, run_end = None, False
        if self.p.replay_mode:
            if not is_new:
                return
            if run_end:
                self.request_shutdown()
            self._run_replay(
                batch,
                snapshot,
                now,
                ordinal,
                session_close,
                run_end,
                session_reason=session_reason if batch is not None else None,
            )
        else:
            self._run_live(
                batch,
                snapshot,
                now,
                ordinal,
                session_close,
                run_end,
                is_new_batch=is_new,
                session_reason=session_reason if batch is not None else None,
            )
            # _run_live publishes readiness only after a durable GRID/source
            # anchor. A fee-pair fence deliberately leaves that anchor absent,
            # so neither readiness nor its dependent next receipt may escape.
            next_callback = getattr(self.p, "live_next_callback", None)
            capture_next = getattr(self, "_capture_live_next_boundary", None)
            if callable(next_callback) and callable(capture_next):
                capture_next(batch, snapshot)

    def _stop_control_refresh_loop(self) -> None:
        """Join runner-owned Store refresh work before Cerebro tears down I/O."""
        if self._control_refresh_stopped:
            return
        refresh_loop = self.p.control_refresh_loop
        if refresh_loop is None:
            self._control_refresh_stopped = True
            return
        refresh_loop.stop_and_join()
        self._control_refresh_stopped = True

    def _confirm_shutdown_post_join(self) -> None:
        """Recheck current source facts after refresh joins, before Store teardown."""

        self._shutdown_post_join_confirmed_state = False
        self._shutdown_post_join_blocker_state = "SHUTDOWN_NOT_REQUESTED"
        if not self._shutdown_requested.is_set():
            return
        if not self._control_refresh_stopped:
            self._shutdown_post_join_blocker_state = (
                self._shutdown_blocker_state
                if self._shutdown_blocker_state == "SHUTDOWN_REFRESH_JOIN_FAILED"
                else "SHUTDOWN_REFRESH_NOT_JOINED"
            )
            return
        if self.p.replay_mode:
            try:
                self._update_replay_shutdown_state()
            except Exception:
                self._shutdown_ready_state = False
                self._shutdown_blocker_state = "REPLAY_SHUTDOWN_FINAL_CHECK_FAILED"
            if not self._shutdown_ready_state:
                self._shutdown_post_join_blocker_state = (
                    self._shutdown_blocker_state or "REPLAY_SHUTDOWN_NOT_READY"
                )
                return
            self._shutdown_post_join_confirmed_state = True
            self._shutdown_post_join_blocker_state = None
            return

        try:
            now = self._clock_now()
            facts = self._live_facts(now)
            self._update_shutdown_state(facts, self.last_order_plan)
        except Exception:
            self._shutdown_ready_state = False
            self._shutdown_blocker_state = "SHUTDOWN_POST_JOIN_CONFIRMATION_FAILED"
        if not self._shutdown_ready_state:
            self._shutdown_post_join_blocker_state = (
                self._shutdown_blocker_state or "SHUTDOWN_POST_JOIN_NOT_READY"
            )
            return
        self._shutdown_post_join_confirmed_state = True
        self._shutdown_post_join_blocker_state = None

    def stop(self) -> None:
        """Join refresh and confirm retirement before Broker/Store teardown."""

        try:
            self._stop_control_refresh_loop()
        except Exception:
            # Do not continue Strategy cleanup while the runner-owned refresh
            # worker may still be using the Store. The caller must retain that
            # resource custody and decide when teardown is safe.
            self._shutdown_ready_state = False
            self._shutdown_blocker_state = "SHUTDOWN_REFRESH_JOIN_FAILED"
            self._shutdown_post_join_confirmed_state = False
            self._shutdown_post_join_blocker_state = "SHUTDOWN_REFRESH_JOIN_FAILED"
            raise

        self._confirm_shutdown_post_join()
        super().stop()

    def notify_order(self, order) -> None:
        status = order.getstatusname().upper()
        self.order_events.append(
            MappingProxyType(
                {
                    "ref": order.ref,
                    "status": status,
                    "instrument": self._routes.get(getattr(order.data, "_name", "")),
                    "executed_size": str(getattr(order.executed, "size", 0)),
                    "executed_price": str(getattr(order.executed, "price", 0)),
                }
            )
        )
        if not self.p.replay_mode:
            self._refresh_live_shutdown_confirmation()
            return
        target_id = next(
            (name for name, data in self._data_by_target.items() if data is order.data), None
        )
        if target_id is None:
            return
        position = self.broker.getposition(order.data)
        quantity = _exact_hands(getattr(position, "size", None))
        info = order.info
        effect = info.get("factor_position_effect")
        if effect == "OPEN" and quantity not in (None, 0):
            owner_id = info.get("replay_owner_intent_id")
            stop = _decimal_or_none(info.get("factor_stop_price"))
            entry_grid = info.get("factor_entry_grid_ordinal")
            if isinstance(owner_id, str) and stop is not None and type(entry_grid) is int:
                self._replay_owners[target_id] = {
                    "owner_intent_id": owner_id,
                    "stop_price": stop,
                    "entry_grid_ordinal": entry_grid,
                    "held_eligible_bars": 0,
                }
        elif effect == "CLOSE" and quantity == 0:
            self._replay_owners.pop(target_id, None)
        if not order.alive():
            self._orders_by_broker_ref.pop(order.ref, None)
        if self._shutdown_requested.is_set():
            self._update_replay_shutdown_state()

    def notify_trade(self, trade) -> None:
        self.trade_events.append(
            MappingProxyType(
                {
                    "ref": trade.ref,
                    "status": "CLOSED" if trade.isclosed else "OPEN",
                    "size": str(trade.size),
                    "price": str(trade.price),
                    "pnl": str(trade.pnl),
                    "pnlcomm": str(trade.pnlcomm),
                }
            )
        )
        if self.p.replay_mode:
            if self._shutdown_requested.is_set():
                self._update_replay_shutdown_state()
        else:
            self._refresh_live_shutdown_confirmation()


__all__ = (
    "Alpha003AccountRiskFact",
    "Alpha003InstrumentRiskFact",
    "Alpha003OpenRiskCandidate",
    "Alpha003OpenRiskLegCandidate",
    "Alpha003OrderAction",
    "Alpha003OrderPlan",
    "Alpha003OrderPlanningInput",
    "Alpha003PolicyInput",
    "Alpha003PositionFact",
    "Alpha003QuoteFact",
    "Alpha003ReplayQuoteFact",
    "Alpha003RiskPolicy",
    "Alpha003SignalTarget",
    "Alpha003TargetDecision",
    "Alpha003TargetStrategy",
    "Alpha003WorkingOrderFact",
    "CohortBatchFacts",
    "DEFAULT_DIRECTION",
    "DEFAULT_FACTOR_MODE",
    "DEFAULT_PREHEAT_BARS",
    "DEFAULT_REBALANCE_GRIDS",
    "FACTOR_NAME",
    "FACTOR_PANEL_LINE",
    "FACTOR_FREQUENCY",
    "FactorPoint",
    "FactorSnapshotFacts",
    "make_alpha003_factor_spec",
    "make_alpha003_live_plan",
    "plan_alpha003_orders",
    "policy_input_from_shared_snapshot",
    "_preselection_block_reason",
    "select_alpha003_targets",
)
