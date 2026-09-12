"""Pure timing and risk projections for the 014_1 offline example.

This module contains no broker, Store, SDK, account, or order transport.  It
only turns explicitly supplied frozen bar and execution facts into conservative
local projections.  In particular, a closed OHLC bar never becomes an
intrabar fill fact and a local flat callback never becomes authoritative flat.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
from decimal import Decimal, ROUND_CEILING, ROUND_FLOOR, InvalidOperation
from typing import Any, Callable, Mapping

NANOSECOND = 1_000_000_000
FIRST_SEND_SECONDS = 1
COMPLETION_SECONDS = 60
DEFAULT_MINIMUM_HOLD_SECONDS = 30 * 60
DEFAULT_MAXIMUM_HOLD_SECONDS = 120 * 60
DEFAULT_MAX_RISK_BAR_AGE_SECONDS = 15 * 60 + 10


class TimingContractError(ValueError):
    """Raised when a timing/risk input is absent, contradictory, or unsafe."""


class ClockSafetyError(TimingContractError):
    """Raised when a monotonic observation cannot be compared safely."""


_MISSING = object()


def _read(value: Any, names: tuple[str, ...], default: Any = _MISSING) -> Any:
    if isinstance(value, Mapping):
        for name in names:
            if name in value:
                return value[name]
    else:
        for name in names:
            if hasattr(value, name):
                return getattr(value, name)
    if default is not _MISSING:
        return default
    raise TimingContractError(f"missing required field: {names[0]}")


def _finite(value: Any, name: str, *, positive: bool = False, nonnegative: bool = False) -> float:
    if isinstance(value, bool):
        raise TimingContractError(f"{name} must not be bool")
    try:
        result = float(value)
    except (TypeError, ValueError) as exc:
        raise TimingContractError(f"{name} must be finite") from exc
    if not math.isfinite(result):
        raise TimingContractError(f"{name} must be finite")
    if positive and result <= 0:
        raise TimingContractError(f"{name} must be positive")
    if nonnegative and result < 0:
        raise TimingContractError(f"{name} must be nonnegative")
    return result


def _integer(value: Any, name: str, *, positive: bool = False, nonnegative: bool = False) -> int:
    if type(value) is not int:
        raise TimingContractError(f"{name} must be an integer")
    if positive and value <= 0:
        raise TimingContractError(f"{name} must be positive")
    if nonnegative and value < 0:
        raise TimingContractError(f"{name} must be nonnegative")
    return value


def _text(value: Any, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise TimingContractError(f"{name} must be non-empty text")
    return value


def _utc(value: datetime, name: str) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise TimingContractError(f"{name} must be timezone-aware")
    return value.astimezone(timezone.utc)


def _tick_round(value: float, tick: float, rounding: str) -> float:
    """Round a finite price on a Decimal string boundary."""

    try:
        decimal_value = Decimal(str(value))
        decimal_tick = Decimal(str(tick))
        quotient = decimal_value / decimal_tick
        rounded = quotient.to_integral_value(
            rounding=ROUND_CEILING if rounding == "ceil" else ROUND_FLOOR
        )
        result = rounded * decimal_tick
    except (InvalidOperation, ValueError) as exc:
        raise TimingContractError("price cannot be rounded to its tick") from exc
    result_float = float(result)
    if not math.isfinite(result_float):
        raise TimingContractError("rounded price must be finite")
    return result_float


@dataclass(frozen=True)
class ClockObservation:
    """One trusted observation in one monotonic clock domain."""

    monotonic_ns: int
    wall_utc: datetime | None
    domain: str
    generation: int = 1
    trusted: bool = True
    source: str | None = None
    boot_id: str | None = None
    scope: Any = None
    mapping_id: str | None = None
    mapping_anchor_mono_ns: int | None = None
    mapping_anchor_wall_utc: datetime | None = None
    mapping_error_ns: int = 0
    mapping_valid_until_mono_ns: int | None = None
    session_open: bool | None = None
    price_limits_known: bool | None = None
    session_scope: Any = None
    price_limits_scope: Any = None
    price_limits_source: str | None = None
    price_limits_reference_identity: str | None = None

    def __post_init__(self) -> None:
        _integer(self.monotonic_ns, "monotonic_ns", nonnegative=True)
        _text(self.domain, "domain")
        _integer(self.generation, "generation", positive=True)
        if type(self.trusted) is not bool:
            raise TimingContractError("trusted must be bool")
        if self.source is not None:
            _text(self.source, "source")
        if self.boot_id is not None:
            _text(self.boot_id, "boot_id")
        if self.mapping_id is not None:
            _text(self.mapping_id, "mapping_id")
        if self.mapping_anchor_mono_ns is not None:
            _integer(self.mapping_anchor_mono_ns, "mapping_anchor_mono_ns", nonnegative=True)
        if self.mapping_error_ns < 0 or type(self.mapping_error_ns) is not int:
            raise TimingContractError("mapping_error_ns must be a non-negative integer")
        if self.mapping_valid_until_mono_ns is not None:
            _integer(
                self.mapping_valid_until_mono_ns,
                "mapping_valid_until_mono_ns",
                nonnegative=True,
            )
        if self.mapping_anchor_wall_utc is not None:
            object.__setattr__(
                self,
                "mapping_anchor_wall_utc",
                _utc(self.mapping_anchor_wall_utc, "mapping_anchor_wall_utc"),
            )
        if self.mapping_anchor_mono_ns is None and self.mapping_anchor_wall_utc is not None:
            raise TimingContractError("mapping anchor requires monotonic time")
        if self.mapping_anchor_mono_ns is not None and self.mapping_anchor_wall_utc is None:
            raise TimingContractError("mapping anchor requires wall time")
        if self.mapping_valid_until_mono_ns is not None and self.mapping_anchor_mono_ns is not None:
            if self.mapping_valid_until_mono_ns <= self.mapping_anchor_mono_ns:
                raise TimingContractError("mapping validity must extend beyond its anchor")
        if self.session_open is not None and type(self.session_open) is not bool:
            raise TimingContractError("session_open must be bool when provided")
        if self.price_limits_known is not None and type(self.price_limits_known) is not bool:
            raise TimingContractError("price_limits_known must be bool when provided")
        if self.price_limits_source is not None:
            _text(self.price_limits_source, "price_limits_source")
        if self.price_limits_reference_identity is not None:
            _text(self.price_limits_reference_identity, "price_limits_reference_identity")
        if self.wall_utc is not None:
            object.__setattr__(self, "wall_utc", _utc(self.wall_utc, "wall_utc"))

    @classmethod
    def from_value(cls, value: Any) -> "ClockObservation":
        if isinstance(value, cls):
            return value
        monotonic_ns = _read(value, ("monotonic_ns", "now_monotonic_ns", "mono_ns"))
        wall_utc = _read(value, ("wall_utc", "now_utc", "now_epoch"), default=None)
        if isinstance(wall_utc, str):
            try:
                wall_utc = datetime.fromisoformat(wall_utc.replace("Z", "+00:00"))
            except ValueError as exc:
                raise TimingContractError("wall_utc must be an ISO timestamp") from exc
        if isinstance(wall_utc, (int, float)) and not isinstance(wall_utc, bool):
            if not math.isfinite(float(wall_utc)):
                raise TimingContractError("wall_utc epoch must be finite")
            wall_utc = datetime.fromtimestamp(float(wall_utc), tz=timezone.utc)
        domain = _read(value, ("domain", "clock_domain", "clock_domain_id"))
        generation = _read(value, ("generation", "connection_generation"), default=_MISSING)
        if generation is _MISSING:
            raise TimingContractError("clock generation is required for an external observation")
        trusted = _read(value, ("trusted", "freshness_verified"), default=False)
        source = _read(
            value,
            ("source", "trust_source", "source_identity", "issuer"),
            default=None,
        )
        boot_id = _read(value, ("boot_id", "clock_boot_id", "session_boot_id"), default=None)
        scope = _read(value, ("scope", "decision_scope", "clock_scope"), default=None)
        mapping_id = _read(value, ("mapping_id",), default=None)
        mapping_anchor_mono_ns = _read(
            value, ("mapping_anchor_mono_ns", "mono_ns_at_anchor"), default=None
        )
        mapping_anchor_wall_utc = _read(
            value, ("mapping_anchor_wall_utc", "wall_utc_at_anchor"), default=None
        )
        mapping_error_ns = _read(value, ("mapping_error_ns", "error_bound_ns"), default=0)
        mapping_valid_until_mono_ns = _read(
            value, ("mapping_valid_until_mono_ns", "valid_until_mono_ns"), default=None
        )
        session_open = _read(value, ("session_open",), default=None)
        price_limits_known = _read(value, ("price_limits_known",), default=None)
        session_scope = _read(value, ("session_scope",), default=None)
        price_limits_scope = _read(value, ("price_limits_scope",), default=None)
        price_limits_source = _read(value, ("price_limits_source",), default=None)
        price_limits_reference_identity = _read(
            value, ("price_limits_reference_identity", "reference_identity"), default=None
        )
        return cls(
            monotonic_ns,
            wall_utc,
            domain,
            generation=generation,
            trusted=trusted,
            source=source,
            boot_id=boot_id,
            scope=scope,
            mapping_id=mapping_id,
            mapping_anchor_mono_ns=mapping_anchor_mono_ns,
            mapping_anchor_wall_utc=mapping_anchor_wall_utc,
            mapping_error_ns=mapping_error_ns,
            mapping_valid_until_mono_ns=mapping_valid_until_mono_ns,
            session_open=session_open,
            price_limits_known=price_limits_known,
            session_scope=session_scope,
            price_limits_scope=price_limits_scope,
            price_limits_source=price_limits_source,
            price_limits_reference_identity=price_limits_reference_identity,
        )

    @property
    def clock_domain_id(self) -> str:
        return self.domain


@dataclass
class ScopedClock:
    """A fail-closed monotonic clock guard for tick and no-bar idle checks."""

    provider: Callable[[], Any] | None = None
    _domain: str | None = field(default=None, init=False)
    _generation: int | None = field(default=None, init=False)
    _boot_id: str | None = field(default=None, init=False)
    _source: str | None = field(default=None, init=False)
    _last: ClockObservation | None = field(default=None, init=False)
    _latched_reason: str | None = field(default=None, init=False)

    @property
    def rejection_reason(self) -> str | None:
        return self._latched_reason

    @property
    def last(self) -> ClockObservation | None:
        return self._last

    def observe(self, value: Any = None) -> ClockObservation:
        if self._latched_reason is not None:
            raise ClockSafetyError(self._latched_reason)
        if value is None:
            if self.provider is None:
                self._latch("TRUSTED_CLOCK_REQUIRED")
            try:
                value = self.provider()
            except Exception as exc:  # provider failures are a safety boundary
                self._latch("TRUSTED_CLOCK_INVALID")
                raise ClockSafetyError(self._latched_reason) from exc
        try:
            observation = ClockObservation.from_value(value)
        except TimingContractError as exc:
            self._latch("TRUSTED_CLOCK_INVALID")
            raise ClockSafetyError(self._latched_reason) from exc
        if not isinstance(value, ClockObservation) and observation.source is None:
            self._latch("TRUSTED_CLOCK_SOURCE_REQUIRED")
        if observation.trusted is not True:
            self._latch("TRUSTED_CLOCK_UNVERIFIED")
        if self._source is not None and observation.source != self._source:
            self._latch("CLOCK_SOURCE_CHANGED")
        if self._domain is not None and observation.domain != self._domain:
            self._latch("CLOCK_DOMAIN_CHANGED")
        if self._generation is not None and observation.generation != self._generation:
            self._latch("CLOCK_GENERATION_CHANGED")
        if self._boot_id is not None and observation.boot_id != self._boot_id:
            self._latch("CLOCK_BOOT_CHANGED")
        if self._last is not None and observation.monotonic_ns < self._last.monotonic_ns:
            self._latch("CLOCK_REGRESSION")
        if self._last is None:
            self._domain = observation.domain
            self._generation = observation.generation
            self._boot_id = observation.boot_id
            self._source = observation.source
            if observation.wall_utc is not None:
                observation = replace(
                    observation,
                    mapping_anchor_mono_ns=observation.monotonic_ns,
                    mapping_anchor_wall_utc=observation.wall_utc,
                    mapping_error_ns=observation.mapping_error_ns,
                    mapping_valid_until_mono_ns=observation.mapping_valid_until_mono_ns,
                )
        elif (
            observation.mapping_anchor_mono_ns is None
            and self._last.mapping_anchor_mono_ns is not None
        ):
            observation = replace(
                observation,
                mapping_id=observation.mapping_id or self._last.mapping_id,
                mapping_anchor_mono_ns=self._last.mapping_anchor_mono_ns,
                mapping_anchor_wall_utc=self._last.mapping_anchor_wall_utc,
                mapping_error_ns=max(observation.mapping_error_ns, self._last.mapping_error_ns),
                mapping_valid_until_mono_ns=(
                    observation.mapping_valid_until_mono_ns
                    or self._last.mapping_valid_until_mono_ns
                ),
            )
        self._domain = observation.domain
        self._last = observation
        return observation

    def now(self) -> ClockObservation:
        return self.observe()

    def _latch(self, reason: str) -> None:
        self._latched_reason = reason
        raise ClockSafetyError(reason)

    @staticmethod
    def deadline_delta_ns(anchor_ns: int, current_ns: int) -> int:
        return _integer(current_ns, "current_ns", nonnegative=True) - _integer(
            anchor_ns, "anchor_ns", nonnegative=True
        )


@dataclass(frozen=True)
class BarPriceEnvelope:
    """Frozen bar-derived price range for one leg."""

    symbol: str
    tick: float
    half_envelope: float
    lower: float
    upper: float
    scope: str
    exchange_limits_known: bool = False
    limit_source: str = "bar_only_unverified"
    reference_identity: str = "bar-only-unverified"

    def __post_init__(self) -> None:
        _text(self.symbol, "symbol")
        _finite(self.tick, "tick", positive=True)
        _finite(self.half_envelope, "half_envelope", positive=True)
        lower = _finite(self.lower, "lower", positive=True)
        upper = _finite(self.upper, "upper", positive=True)
        if lower > upper:
            raise TimingContractError("price envelope is empty")
        _text(self.scope, "scope")
        if type(self.exchange_limits_known) is not bool:
            raise TimingContractError("exchange_limits_known must be bool")
        _text(self.limit_source, "limit_source")
        _text(self.reference_identity, "reference_identity")

    @property
    def execution_eligible(self) -> bool:
        return self.exchange_limits_known


def freeze_bar_envelopes(
    bars: Mapping[str, Mapping[str, Any]],
    *,
    ticks: Mapping[str, Any],
    scope: str,
    exchange_limits: Mapping[str, Mapping[str, Any]] | None = None,
) -> dict[str, BarPriceEnvelope]:
    """Freeze ``h=max(2*tick,.25*(high-low))`` and its legal intersection."""

    _text(scope, "scope")
    if not isinstance(bars, Mapping) or not bars:
        raise TimingContractError("bars must be a non-empty mapping")
    if not isinstance(ticks, Mapping):
        raise TimingContractError("ticks must be a mapping")
    if exchange_limits is not None and not isinstance(exchange_limits, Mapping):
        raise TimingContractError("exchange_limits must be a mapping")
    frozen: dict[str, BarPriceEnvelope] = {}
    for raw_symbol, raw_bar in bars.items():
        symbol = _text(raw_symbol, "symbol")
        if not isinstance(raw_bar, Mapping):
            raise TimingContractError(f"bar for {symbol} must be a mapping")
        tick = _finite(ticks.get(symbol), f"{symbol}.tick", positive=True)
        close = _finite(raw_bar.get("close"), f"{symbol}.close", positive=True)
        high = _finite(raw_bar.get("high"), f"{symbol}.high", positive=True)
        low = _finite(raw_bar.get("low"), f"{symbol}.low", positive=True)
        if high < low:
            raise TimingContractError(f"{symbol} high is below low")
        half = max(2.0 * tick, 0.25 * (high - low))
        lower = _tick_round(close - half, tick, "floor")
        upper = _tick_round(close + half, tick, "ceil")
        known = False
        source = "bar_only_unverified"
        reference_identity = "bar-only-unverified"
        if exchange_limits is not None:
            raw_limits = exchange_limits.get(symbol)
            if not isinstance(raw_limits, Mapping):
                raise TimingContractError(f"{symbol} exchange limits are missing")
            legal_lower = _finite(
                raw_limits.get("lower", raw_limits.get("lower_limit")),
                f"{symbol}.lower_limit",
                positive=True,
            )
            legal_upper = _finite(
                raw_limits.get("upper", raw_limits.get("upper_limit")),
                f"{symbol}.upper_limit",
                positive=True,
            )
            if legal_lower > legal_upper:
                raise TimingContractError(f"{symbol} exchange limits are inverted")
            source = _text(
                raw_limits.get("source", raw_limits.get("reference_identity", "")),
                f"{symbol}.limit_source",
            )
            reference_identity = _text(
                raw_limits.get("reference_identity", source), f"{symbol}.reference_identity"
            )
            lower = max(lower, _tick_round(legal_lower, tick, "ceil"))
            upper = min(upper, _tick_round(legal_upper, tick, "floor"))
            known = lower <= upper
        if lower > upper:
            raise TimingContractError(f"{symbol} bar and exchange envelopes do not intersect")
        frozen[symbol] = BarPriceEnvelope(
            symbol=symbol,
            tick=tick,
            half_envelope=half,
            lower=lower,
            upper=upper,
            scope=scope,
            exchange_limits_known=known,
            limit_source=source,
            reference_identity=reference_identity,
        )
    return frozen


freeze_price_envelopes = freeze_bar_envelopes


def compute_bar_envelope(
    *,
    close: Any,
    high: Any,
    low: Any,
    tick: Any,
    symbol: str = "LEG",
    scope: str = "bar-only",
    exchange_limits: Mapping[str, Any] | None = None,
) -> BarPriceEnvelope:
    """Single-leg convenience wrapper used by offline arithmetic probes."""

    limits = None
    if exchange_limits is not None:
        limits = {symbol: exchange_limits}
    return freeze_bar_envelopes(
        {symbol: {"close": close, "high": high, "low": low}},
        ticks={symbol: tick},
        scope=scope,
        exchange_limits=limits,
    )[symbol]


def price_allowed(envelope: BarPriceEnvelope, side: str, price: Any) -> bool:
    if not isinstance(envelope, BarPriceEnvelope):
        raise TimingContractError("envelope is required")
    if side not in {"buy", "sell"}:
        raise TimingContractError("side must be buy or sell")
    candidate = _finite(price, "price", positive=True)
    return envelope.lower <= candidate <= envelope.upper


def execution_price_allowed(envelope: BarPriceEnvelope, side: str, price: Any) -> bool:
    """Apply the envelope only when current legal limits are explicitly known."""

    if not envelope.exchange_limits_known:
        return False
    return price_allowed(envelope, side, price)


@dataclass(frozen=True)
class EconomicScore:
    direction: str
    gross_cny: float
    total_cost_cny: float
    net_cny: float
    eligible: bool
    complete_cost_evidence: bool = True


def _direction_cost(
    direction: str,
    total_costs: Mapping[str, Any] | None,
    fee_schedule: Mapping[str, Any] | None,
    reserves: Mapping[str, Any] | None,
) -> tuple[float, bool]:
    if fee_schedule is not None:
        if not isinstance(fee_schedule, Mapping):
            raise TimingContractError("fee_schedule must be a mapping")
        required = (
            "open_buy",
            "open_sell",
            "close_buy",
            "close_sell",
            "close_today_buy",
            "close_today_sell",
        )
        values = [
            _finite(fee_schedule.get(key), f"fee_schedule.{key}", nonnegative=True)
            for key in required
        ]
        cost = sum(values)
        if reserves:
            for key, value in reserves.items():
                cost += _finite(value, f"reserve.{key}", nonnegative=True)
        return cost, True
    if not isinstance(total_costs, Mapping) or direction not in total_costs:
        raise TimingContractError(f"complete costs required for {direction}")
    raw = total_costs[direction]
    if isinstance(raw, Mapping):
        if not raw:
            raise TimingContractError(f"complete costs required for {direction}")
        return (
            sum(_finite(value, f"{direction}.cost", nonnegative=True) for value in raw.values()),
            True,
        )
    return _finite(raw, f"{direction}.cost", nonnegative=True), True


def economic_scores(
    envelopes: Mapping[str, BarPriceEnvelope],
    *,
    multiplier: Any,
    discount: Any,
    strike: Any,
    total_costs: Mapping[str, Any] | None = None,
    fee_schedule: Mapping[str, Any] | None = None,
    reserves: Mapping[str, Any] | None = None,
    minimum_score: float = 20.0,
) -> dict[str, EconomicScore]:
    """Compute both direction scores with a strict ``net > minimum`` gate."""

    for symbol in ("F", "C", "P"):
        if symbol not in envelopes:
            raise TimingContractError(f"missing envelope role {symbol}")
    multiple = _finite(multiplier, "multiplier", positive=True)
    delta = _finite(discount, "discount")
    strike_value = _finite(strike, "strike", positive=True)
    threshold = _finite(minimum_score, "minimum_score")
    f, c, p = envelopes["F"], envelopes["C"], envelopes["P"]
    gross_conversion = multiple * (c.lower - p.upper - delta * (f.upper - strike_value))
    gross_reversal = multiple * (p.lower - c.upper + delta * (f.lower - strike_value))
    result: dict[str, EconomicScore] = {}
    for direction, gross in (("conversion", gross_conversion), ("reversal", gross_reversal)):
        cost, complete = _direction_cost(direction, total_costs, fee_schedule, reserves)
        net = gross - cost
        result[direction] = EconomicScore(
            direction=direction,
            gross_cny=gross,
            total_cost_cny=cost,
            net_cny=net,
            eligible=complete and net > threshold,
            complete_cost_evidence=complete,
        )
    return result


calculate_economic_scores = economic_scores


@dataclass(frozen=True)
class TimingGate:
    status: str
    stage: str
    now_ns: int
    deadline_ns: int
    reason: str


@dataclass
class ExecutionWindow:
    """Immutable-deadline projection for one decision token."""

    decision_mono_ns: int
    first_send_seconds: int = FIRST_SEND_SECONDS
    completion_seconds: int = COMPLETION_SECONDS
    first_send_deadline_ns: int = field(init=False)
    completion_deadline_ns: int = field(init=False)
    _ack_observations: list[int] = field(default_factory=list, init=False, repr=False)

    def __post_init__(self) -> None:
        _integer(self.decision_mono_ns, "decision_mono_ns", nonnegative=True)
        _integer(self.first_send_seconds, "first_send_seconds", positive=True)
        _integer(self.completion_seconds, "completion_seconds", positive=True)
        if self.first_send_seconds > self.completion_seconds:
            raise TimingContractError("first-send deadline cannot exceed completion deadline")
        self.first_send_deadline_ns = self.decision_mono_ns + self.first_send_seconds * NANOSECOND
        self.completion_deadline_ns = self.decision_mono_ns + self.completion_seconds * NANOSECOND

    def gate(self, now_ns: int, stage: str, *, possible_exposure: bool = False) -> TimingGate:
        now = _integer(now_ns, "now_ns", nonnegative=True)
        if stage in {"first_send", "first_leg", "send_first_leg"}:
            deadline = self.first_send_deadline_ns
            if now <= deadline:
                return TimingGate("ELIGIBLE_FOR_OTHER_GATES", stage, now, deadline, "within_1s")
            status = "RECOVERY_REQUIRED" if possible_exposure else "REJECT_NEW_ORDINARY_WRITE"
            return TimingGate(status, stage, now, deadline, "first_send_deadline_expired")
        if stage not in {"remaining_legs", "completion", "complete"}:
            raise TimingContractError("unknown execution timing stage")
        deadline = self.completion_deadline_ns
        if now <= deadline:
            return TimingGate("ELIGIBLE_FOR_OTHER_GATES", stage, now, deadline, "within_60s")
        return TimingGate(
            "RECOVERY_REQUIRED" if possible_exposure else "REJECT_TARGET_COMPLETION",
            stage,
            now,
            deadline,
            "completion_deadline_expired",
        )

    def observe_ack(self, now_ns: int) -> None:
        """Record an ACK observation without moving either deadline."""

        self._ack_observations.append(_integer(now_ns, "ack_now_ns", nonnegative=True))

    def projection(self) -> dict[str, int]:
        return {
            "decision_mono_ns": self.decision_mono_ns,
            "first_send_deadline_ns": self.first_send_deadline_ns,
            "completion_deadline_ns": self.completion_deadline_ns,
        }

    @property
    def first_leg_deadline_ns(self) -> int:
        return self.first_send_deadline_ns

    @property
    def remaining_leg_deadline_ns(self) -> int:
        return self.completion_deadline_ns

    def check_first_send(self, now_ns: int, *, possible_exposure: bool = False) -> TimingGate:
        return self.gate(now_ns, "first_send", possible_exposure=possible_exposure)

    def check_completion(self, now_ns: int, *, possible_exposure: bool = False) -> TimingGate:
        return self.gate(now_ns, "remaining_legs", possible_exposure=possible_exposure)


@dataclass(frozen=True)
class ExecutionFact:
    """A supplied execution fact; accepted/ACK status is not a fill."""

    leg: str
    quantity: float
    status: str
    fill_lower_ns: int | None = None
    fill_upper_ns: int | None = None
    source: str = "unknown"
    clock_domain: str | None = None
    generation: int | None = None
    decision_id: str | None = None
    basket_id: str | None = None
    order_id: str | None = None
    fact_id: str | None = None
    source_identity: str | None = None
    quantity_kind: str = "incremental"

    def __post_init__(self) -> None:
        _text(self.leg, "leg")
        quantity = _finite(self.quantity, "quantity", nonnegative=True)
        if quantity == 0:
            raise TimingContractError("quantity must be positive")
        if self.status not in {"accepted", "ack", "partial", "completed", "canceled", "unknown"}:
            raise TimingContractError("unknown execution status")
        _text(self.source, "source")
        for name in (
            "clock_domain",
            "decision_id",
            "basket_id",
            "order_id",
            "fact_id",
            "source_identity",
        ):
            value = getattr(self, name)
            if value is not None:
                _text(value, name)
        if self.generation is not None:
            _integer(self.generation, "generation", positive=True)
        if self.quantity_kind not in {"incremental", "cumulative"}:
            raise TimingContractError("quantity_kind must be incremental or cumulative")
        if (self.fill_lower_ns is None) != (self.fill_upper_ns is None):
            raise TimingContractError("fill interval must contain both bounds")
        if self.fill_lower_ns is not None:
            lower = _integer(self.fill_lower_ns, "fill_lower_ns", nonnegative=True)
            upper = _integer(self.fill_upper_ns, "fill_upper_ns", nonnegative=True)
            if lower > upper:
                raise TimingContractError("fill interval is inverted")

    @property
    def timestamped_fill(self) -> bool:
        return (
            self.status == "completed"
            and self.fill_lower_ns is not None
            and (
                self.source == "synthetic_timestamped_execution"
                or self.source.startswith("synthetic_")
                or self.source in {"synthetic", "offline_fixture"}
            )
        )

    @property
    def identity_key(self) -> tuple[Any, ...]:
        """Stable idempotency key for one raw execution observation."""

        if self.fact_id is not None:
            return ("fact_id", self.fact_id)
        return (
            "fact",
            self.leg,
            self.quantity,
            self.status,
            self.fill_lower_ns,
            self.fill_upper_ns,
            self.source,
            self.clock_domain,
            self.generation,
            self.decision_id,
            self.basket_id,
            self.order_id,
            self.source_identity,
            self.quantity_kind,
        )


@dataclass(frozen=True)
class FillTimingResult:
    status: str
    confirmed_quantity: float
    possible_exposure: bool = False
    reason: str = ""
    source: str = "bar_only"


def classify_bar_only_fill(
    *,
    decision_mono_ns: int,
    next_bar_seconds: float,
    execution_window_seconds: float,
    touched: bool,
    volume: float,
) -> FillTimingResult:
    """Never infer a 60-second fill from a later 15-minute OHLC bar."""

    _integer(decision_mono_ns, "decision_mono_ns", nonnegative=True)
    _finite(next_bar_seconds, "next_bar_seconds", positive=True)
    _finite(execution_window_seconds, "execution_window_seconds", positive=True)
    if type(touched) is not bool:
        raise TimingContractError("touched must be bool")
    _finite(volume, "volume", nonnegative=True)
    return FillTimingResult(
        status="FILL_TIMING_UNKNOWN",
        confirmed_quantity=0,
        possible_exposure=False,
        reason="closed_ohlc_does_not_order_events_inside_ttl",
        source="bar_only",
    )


def classify_execution_facts(
    facts: tuple[ExecutionFact, ...] | list[ExecutionFact],
    *,
    deadline_ns: int,
    expected_clock_domain: str | None = None,
    expected_generation: int | None = None,
    decision_mono_ns: int | None = None,
) -> FillTimingResult:
    deadline = _integer(deadline_ns, "deadline_ns", nonnegative=True)
    if expected_clock_domain is not None:
        _text(expected_clock_domain, "expected_clock_domain")
    if expected_generation is not None:
        _integer(expected_generation, "expected_generation", positive=True)
    if decision_mono_ns is not None:
        _integer(decision_mono_ns, "decision_mono_ns", nonnegative=True)
    confirmed = 0.0
    possible = False
    seen: set[tuple[Any, ...]] = set()
    for fact in facts:
        if not isinstance(fact, ExecutionFact):
            raise TimingContractError("execution facts must be ExecutionFact values")
        if fact.identity_key in seen:
            continue
        seen.add(fact.identity_key)
        if fact.status in {"accepted", "ack", "partial", "unknown"}:
            possible = True
        if expected_clock_domain is not None or expected_generation is not None:
            if fact.clock_domain != expected_clock_domain or fact.generation != expected_generation:
                possible = True
                continue
        if fact.timestamped_fill:
            if (
                decision_mono_ns is not None and fact.fill_lower_ns < decision_mono_ns
            ) or fact.fill_upper_ns > deadline:
                possible = True
                continue
            confirmed += fact.quantity
    if confirmed:
        return FillTimingResult(
            status="TIMESTAMPED_SYNTHETIC_ONLY",
            confirmed_quantity=confirmed,
            possible_exposure=possible,
            source="synthetic_timestamped_execution",
        )
    return FillTimingResult(
        status="FILL_TIMING_UNKNOWN" if possible else "NO_CONFIRMED_FILL",
        confirmed_quantity=0,
        possible_exposure=possible,
        reason="accepted_or_ack_is_not_a_fill",
        source="execution_facts",
    )


@dataclass
class HoldProjection:
    """Conservative normal/risk hold deadlines for a single basket."""

    expected_legs: tuple[str, ...]
    minimum_hold_seconds: int = DEFAULT_MINIMUM_HOLD_SECONDS
    maximum_hold_seconds: int = DEFAULT_MAXIMUM_HOLD_SECONDS
    _first_possible_lower_ns: int | None = field(default=None, init=False, repr=False)
    _fill_upper_by_leg: dict[str, int] = field(default_factory=dict, init=False, repr=False)

    def __post_init__(self) -> None:
        if not self.expected_legs or len(set(self.expected_legs)) != len(self.expected_legs):
            raise TimingContractError("expected_legs must be distinct and non-empty")
        self.minimum_hold_seconds = _integer(
            self.minimum_hold_seconds, "minimum_hold_seconds", positive=True
        )
        self.maximum_hold_seconds = _integer(
            self.maximum_hold_seconds, "maximum_hold_seconds", positive=True
        )
        if self.maximum_hold_seconds > DEFAULT_MAXIMUM_HOLD_SECONDS:
            raise TimingContractError("maximum_hold_seconds must be at most 120 minutes")
        if self.maximum_hold_seconds < self.minimum_hold_seconds:
            raise TimingContractError("maximum hold cannot be below minimum hold")

    def record_possible_exposure(self, leg: str, *, lower_ns: int) -> None:
        if leg not in self.expected_legs:
            raise TimingContractError("unknown basket leg")
        lower = _integer(lower_ns, "possible exposure lower bound", nonnegative=True)
        if self._first_possible_lower_ns is None or lower < self._first_possible_lower_ns:
            self._first_possible_lower_ns = lower

    def record_confirmed_fill(self, leg: str, fill_lower_ns: int, fill_upper_ns: int) -> None:
        if leg not in self.expected_legs:
            raise TimingContractError("unknown basket leg")
        lower = _integer(fill_lower_ns, "fill lower bound", nonnegative=True)
        upper = _integer(fill_upper_ns, "fill upper bound", nonnegative=True)
        if lower > upper:
            raise TimingContractError("fill interval is inverted")
        self._fill_upper_by_leg[leg] = upper

    def record_fill_interval(self, leg: str, interval: tuple[int, int]) -> None:
        if not isinstance(interval, (tuple, list)) or len(interval) != 2:
            raise TimingContractError("fill interval must be a two-item tuple")
        self.record_confirmed_fill(leg, interval[0], interval[1])

    @property
    def minimum_deadline_ns(self) -> int | None:
        if set(self._fill_upper_by_leg) != set(self.expected_legs):
            return None
        return max(self._fill_upper_by_leg.values()) + self.minimum_hold_seconds * NANOSECOND

    @property
    def maximum_deadline_ns(self) -> int | None:
        if self._first_possible_lower_ns is None:
            return None
        return self._first_possible_lower_ns + self.maximum_hold_seconds * NANOSECOND

    def normal_exit_allowed(self, now_ns: int) -> bool:
        deadline = self.minimum_deadline_ns
        return deadline is not None and _integer(now_ns, "now_ns", nonnegative=True) >= deadline

    def risk_exit_allowed(self, now_ns: int) -> bool:
        deadline = self.maximum_deadline_ns
        return deadline is not None and _integer(now_ns, "now_ns", nonnegative=True) >= deadline

    def projection(self) -> dict[str, Any]:
        return {
            "minimum_deadline_ns": self.minimum_deadline_ns,
            "maximum_deadline_ns": self.maximum_deadline_ns,
            "first_possible_exposure_lower_ns": self._first_possible_lower_ns,
            "confirmed_fill_upper_ns": dict(self._fill_upper_by_leg),
            "risk_exit_ignores_minimum_hold": True,
        }

    @property
    def min_hold_deadline_ns(self) -> int | None:
        return self.minimum_deadline_ns

    @property
    def max_hold_deadline_ns(self) -> int | None:
        return self.maximum_deadline_ns

    @property
    def first_possible_exposure_mono_ns(self) -> int | None:
        return self._first_possible_lower_ns

    def can_normal_exit(self, now_ns: int) -> bool:
        return self.normal_exit_allowed(now_ns)

    def risk_due(self, now_ns: int) -> bool:
        return self.risk_exit_allowed(now_ns)


@dataclass
class ConfirmationProjection:
    required: int = 2
    bar_interval_seconds: int = 15 * 60
    _scope: Any = field(default=None, init=False)
    _direction: str | None = field(default=None, init=False)
    _last_key: Any = field(default=None, init=False)
    _count: int = field(default=0, init=False)

    def __post_init__(self) -> None:
        self.required = _integer(self.required, "required confirmations", positive=True)
        self.bar_interval_seconds = _integer(
            self.bar_interval_seconds, "bar_interval_seconds", positive=True
        )

    def reset(self, reason: str | None = None) -> None:
        self._scope = None
        self._direction = None
        self._last_key = None
        self._count = 0

    @property
    def count(self) -> int:
        return self._count

    def _contiguous(self, previous: Any, current: Any) -> bool:
        if previous is None:
            return True
        if isinstance(previous, int) and isinstance(current, int):
            return current == previous + 1
        if isinstance(previous, datetime) and isinstance(current, datetime):
            return (current - previous).total_seconds() == self.bar_interval_seconds
        if isinstance(previous, str) and isinstance(current, str):
            left = re.search(r"(\d+)$", previous)
            right = re.search(r"(\d+)$", current)
            if left and right:
                return int(right.group(1)) == int(left.group(1)) + 1
            return current != previous
        return current != previous

    def accept(self, direction: str, scope: Any, key: Any, *, qualified: bool) -> bool:
        if not qualified:
            self.reset("qualification_failed")
            return False
        if (
            self._scope != scope
            or self._direction != direction
            or not self._contiguous(self._last_key, key)
        ):
            self._scope = scope
            self._direction = direction
            self._last_key = key
            self._count = 1
            return False
        if key == self._last_key:
            self.reset("duplicate")
            return False
        self._last_key = key
        self._count += 1
        if self._count < self.required:
            return False
        self.reset("confirmed")
        return True


@dataclass(frozen=True)
class ExecutionToken:
    candidate: str
    trading_day: str
    session: str
    bar_end: str

    def __post_init__(self) -> None:
        for name in ("candidate", "trading_day", "session", "bar_end"):
            _text(getattr(self, name), name)

    @property
    def canonical(self) -> str:
        return json.dumps(
            {
                "bar_end": self.bar_end,
                "candidate": self.candidate,
                "session": self.session,
                "trading_day": self.trading_day,
            },
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )

    @property
    def digest(self) -> str:
        return hashlib.sha256(self.canonical.encode("utf-8")).hexdigest()


@dataclass
class TokenProjection:
    """Bounded process-local dedup projection; SDK durability remains required."""

    _consumed: set[str] = field(default_factory=set, init=False, repr=False)
    max_tokens: int = 128

    def __post_init__(self) -> None:
        self.max_tokens = _integer(self.max_tokens, "max_tokens", positive=True)

    def consume(self, token: ExecutionToken) -> bool:
        if not isinstance(token, ExecutionToken):
            raise TimingContractError("token must be an ExecutionToken")
        if token.digest in self._consumed:
            return False
        if len(self._consumed) >= self.max_tokens:
            self._consumed.pop()
        self._consumed.add(token.digest)
        return True

    @property
    def durability_status(self) -> str:
        return "SDK_OWNER_REQUIRED"


@dataclass(frozen=True)
class RiskBarProjection:
    status: str
    age_upper_seconds: float
    allowed_actions: tuple[str, ...]
    successful_flat_exit: bool
    reason: str

    @property
    def can_propose_recovery(self) -> bool:
        return self.status == "RECOVERY_PRICE_ELIGIBLE"


@dataclass(frozen=True)
class SessionRiskProjection:
    """Session and loss-trigger projection with unknown facts kept unknown."""

    ordinary_entry_allowed: bool
    ordinary_exit_due: bool
    handover_due: bool
    basket_loss_triggered: bool
    daily_loss_triggered: bool
    account_risk_status: str
    reason: str


@dataclass(frozen=True)
class SessionRiskPolicy:
    """Fixed local session gates; no calendar or account source is invented."""

    stop_entry_seconds: int = 30 * 60
    exit_seconds: int = 10 * 60
    handover_seconds: int = 3 * 60
    basket_loss_limit: float = 150.0
    daily_loss_limit: float = 300.0

    def __post_init__(self) -> None:
        stop_entry = _integer(self.stop_entry_seconds, "stop_entry_seconds", positive=True)
        exit_seconds = _integer(self.exit_seconds, "exit_seconds", positive=True)
        handover = _integer(self.handover_seconds, "handover_seconds", positive=True)
        if stop_entry < 30 * 60:
            raise TimingContractError("stop_entry_seconds must be at least 1800")
        if exit_seconds < 10 * 60:
            raise TimingContractError("exit_seconds must be at least 600")
        if handover < 3 * 60:
            raise TimingContractError("handover_seconds must be at least 180")
        if handover > exit_seconds or exit_seconds > stop_entry:
            raise TimingContractError("session windows must be handover <= exit <= stop-entry")
        object.__setattr__(
            self,
            "basket_loss_limit",
            _finite(self.basket_loss_limit, "basket_loss_limit", positive=True),
        )
        object.__setattr__(
            self,
            "daily_loss_limit",
            _finite(self.daily_loss_limit, "daily_loss_limit", positive=True),
        )

    def evaluate(
        self,
        *,
        now_utc: datetime,
        session_end_utc: datetime,
        basket_loss: Any = None,
        daily_loss: Any = None,
        account_risk_known: bool = False,
        fees_complete: bool = False,
    ) -> SessionRiskProjection:
        now = _utc(now_utc, "now_utc")
        end = _utc(session_end_utc, "session_end_utc")
        if end < now:
            remaining = -1.0
        else:
            remaining = (end - now).total_seconds()
        if type(account_risk_known) is not bool or type(fees_complete) is not bool:
            raise TimingContractError("account_risk_known and fees_complete must be bool")
        basket_triggered = False
        daily_triggered = False
        loss_facts_known = basket_loss is not None and daily_loss is not None
        if loss_facts_known:
            basket_triggered = (
                _finite(basket_loss, "basket_loss", nonnegative=True) >= self.basket_loss_limit
            )
            daily_triggered = (
                _finite(daily_loss, "daily_loss", nonnegative=True) >= self.daily_loss_limit
            )
        account_status = (
            "KNOWN" if account_risk_known and fees_complete and loss_facts_known else "UNKNOWN"
        )
        handover = remaining <= self.handover_seconds
        exit_due = remaining <= self.exit_seconds
        stop_entry = remaining <= self.stop_entry_seconds
        ordinary_allowed = (
            not stop_entry
            and not basket_triggered
            and not daily_triggered
            and account_status == "KNOWN"
        )
        reasons = []
        if stop_entry:
            reasons.append("SESSION_STOP_ENTRY")
        if exit_due:
            reasons.append("SESSION_EXIT_WINDOW")
        if handover:
            reasons.append("SESSION_HANDOVER_WINDOW")
        if basket_triggered:
            reasons.append("BASKET_LOSS_LIMIT")
        if daily_triggered:
            reasons.append("DAILY_LOSS_LIMIT")
        if account_status == "UNKNOWN":
            reasons.append("ACCOUNT_OR_FEE_EVIDENCE_UNKNOWN")
        return SessionRiskProjection(
            ordinary_entry_allowed=ordinary_allowed,
            ordinary_exit_due=exit_due or basket_triggered or daily_triggered,
            handover_due=handover,
            basket_loss_triggered=basket_triggered,
            daily_loss_triggered=daily_triggered,
            account_risk_status=account_status,
            reason="+".join(reasons) or "SESSION_OPEN_AND_RISK_FACTS_KNOWN",
        )


def _mapping_field(mapping: Any, name: str, default: Any = _MISSING) -> Any:
    if mapping is None:
        if default is not _MISSING:
            return default
        raise TimingContractError(f"clock mapping requires {name}")
    if isinstance(mapping, Mapping):
        if name in mapping:
            return mapping[name]
    elif hasattr(mapping, name):
        return getattr(mapping, name)
    if default is not _MISSING:
        return default
    raise TimingContractError(f"clock mapping requires {name}")


def _validate_clock_mapping(mapping: Any, observation: ClockObservation) -> tuple[int, int]:
    """Return mapped bucket-age inputs after validating one frozen mapping pair."""

    mapping_id = _text(_mapping_field(mapping, "mapping_id"), "mapping_id")
    del mapping_id
    anchor_wall = _utc(_mapping_field(mapping, "wall_utc_at_anchor"), "wall_utc_at_anchor")
    anchor_mono = _integer(
        _mapping_field(mapping, "mono_ns_at_anchor"), "mono_ns_at_anchor", nonnegative=True
    )
    domain = _text(
        _mapping_field(mapping, "clock_domain_id", _mapping_field(mapping, "domain", default=None)),
        "clock_domain_id",
    )
    generation = _integer(
        _mapping_field(
            mapping,
            "connection_generation",
            _mapping_field(mapping, "generation", default=None),
        ),
        "connection_generation",
        positive=True,
    )
    source = _text(_mapping_field(mapping, "source"), "clock mapping source")
    error_ns = _integer(
        _mapping_field(
            mapping, "error_bound_ns", _mapping_field(mapping, "mapping_error_ns", default=0)
        ),
        "error_bound_ns",
        nonnegative=True,
    )
    valid_until = _integer(
        _mapping_field(
            mapping,
            "valid_until_mono_ns",
            _mapping_field(mapping, "mapping_valid_until_mono_ns", default=None),
        ),
        "valid_until_mono_ns",
        nonnegative=True,
    )
    rules_hash = _text(_mapping_field(mapping, "rules_hash"), "mapping rules_hash")
    del source, rules_hash
    if valid_until <= anchor_mono:
        raise TimingContractError("clock mapping validity must extend beyond its anchor")
    if observation.domain != domain or observation.generation != generation:
        raise TimingContractError("clock mapping scope does not match observation")
    if observation.monotonic_ns > valid_until:
        raise TimingContractError("clock mapping is expired")
    if observation.wall_utc is None:
        raise TimingContractError("mapping validation requires wall_utc")
    mapped_wall_ns = anchor_mono + int(
        round((observation.wall_utc - anchor_wall).total_seconds() * NANOSECOND)
    )
    if abs(observation.monotonic_ns - mapped_wall_ns) > error_ns:
        raise TimingContractError("clock mapping pair exceeds its error bound")
    return anchor_mono, error_ns


def project_risk_bar(
    *,
    bucket_end: datetime,
    now: ClockObservation | Mapping[str, Any] | Any,
    session_open: bool,
    price_limits_known: bool,
    mapping_error_ns: int = 0,
    max_age_seconds: int = DEFAULT_MAX_RISK_BAR_AGE_SECONDS,
    cancel_authority: bool = False,
    clock_mapping: Any = None,
    scope: Any = None,
    session_evidence: Mapping[str, Any] | None = None,
    price_limits_evidence: Mapping[str, Any] | None = None,
) -> RiskBarProjection:
    """Project pure-K recovery permission from bucket end and a scoped clock."""

    end = _utc(bucket_end, "bucket_end")
    observation = ClockObservation.from_value(now)
    if observation.wall_utc is None:
        raise TimingContractError("risk bar projection requires wall_utc")
    error_ns = _integer(mapping_error_ns, "mapping_error_ns", nonnegative=True)
    max_age = _finite(max_age_seconds, "max_age_seconds", positive=True)
    if max_age > DEFAULT_MAX_RISK_BAR_AGE_SECONDS:
        raise TimingContractError("max_age_seconds must be at most 910")
    if type(session_open) is not bool or type(price_limits_known) is not bool:
        raise TimingContractError("session and price-limit status must be bool")
    if observation.trusted is not True:
        age_upper = float("inf")
    else:
        mapping = clock_mapping
        if mapping is None and observation.mapping_anchor_mono_ns is not None:
            mapping = {
                "mapping_id": observation.mapping_id or "scoped-clock-observation",
                "wall_utc_at_anchor": observation.mapping_anchor_wall_utc,
                "mono_ns_at_anchor": observation.mapping_anchor_mono_ns,
                "clock_domain_id": observation.domain,
                "connection_generation": observation.generation,
                "source": observation.source or "typed-clock-observation",
                "error_bound_ns": observation.mapping_error_ns,
                "valid_until_mono_ns": observation.mapping_valid_until_mono_ns
                or max(observation.monotonic_ns + 1, 2**63 - 1),
                "rules_hash": "scoped-clock-observation",
            }
        try:
            if mapping is not None:
                anchor_mono, mapping_error = _validate_clock_mapping(mapping, observation)
                bucket_delta_ns = int(
                    round(
                        (
                            end - _utc(_mapping_field(mapping, "wall_utc_at_anchor"), "anchor")
                        ).total_seconds()
                        * NANOSECOND
                    )
                )
                age_ns = observation.monotonic_ns - (anchor_mono + bucket_delta_ns)
                age_upper = (age_ns + max(error_ns, mapping_error)) / NANOSECOND
            else:
                raw_age = (observation.wall_utc - end).total_seconds()
                age_upper = raw_age + max(error_ns, observation.mapping_error_ns) / NANOSECOND
        except (TimingContractError, ValueError, OverflowError):
            age_upper = float("inf")
    if scope is not None and observation.scope is not None and observation.scope != scope:
        session_open = False
        price_limits_known = False
    if session_evidence is not None:
        if not isinstance(session_evidence, Mapping):
            raise TimingContractError("session_evidence must be a mapping")
        session_source = session_evidence.get("source")
        if (
            scope is None
            or session_evidence.get("scope") != scope
            or session_evidence.get("generation") != observation.generation
            or not isinstance(session_source, str)
            or not session_source.strip()
        ):
            session_open = False
    if price_limits_evidence is not None:
        if not isinstance(price_limits_evidence, Mapping):
            raise TimingContractError("price_limits_evidence must be a mapping")
        limit_source = price_limits_evidence.get("source")
        reference_identity = price_limits_evidence.get("reference_identity")
        if (
            scope is None
            or price_limits_evidence.get("scope") != scope
            or price_limits_evidence.get("generation") != observation.generation
            or not isinstance(limit_source, str)
            or not limit_source.strip()
            or not isinstance(reference_identity, str)
            or not reference_identity.strip()
        ):
            price_limits_known = False
    eligible = 0 <= age_upper <= max_age and session_open and price_limits_known
    if eligible:
        actions = (
            "propose_recovery_price",
            "query",
            "record_unresolved_exposure",
            "continue_monitoring",
        )
        return RiskBarProjection("RECOVERY_PRICE_ELIGIBLE", age_upper, actions, False, "fresh_bar")
    actions = ["query", "record_unresolved_exposure", "continue_monitoring"]
    if cancel_authority:
        actions.append("cancel")
    reasons = []
    if not math.isfinite(age_upper):
        reasons.append("CLOCK_MAPPING_UNVERIFIED")
    elif age_upper < 0:
        reasons.append("future_bar")
    elif age_upper > max_age:
        reasons.append("BAR_AGE_OVER_910_SECONDS")
    if not session_open:
        reasons.append("SESSION_CLOSED")
    if not price_limits_known:
        reasons.append("PRICE_LIMITS_UNKNOWN")
    return RiskBarProjection(
        "BLOCKED_UNTIL_VALID_EVIDENCE", age_upper, tuple(actions), False, "+".join(reasons)
    )


def replay_fill_status() -> dict[str, Any]:
    """Stable report marker for a bar-only replay with no intrabar evidence."""

    return {
        "status": "FILL_TIMING_UNKNOWN",
        "confirmed_quantity": 0,
        "possible_exposure": False,
        "source": "bar_only",
        "reason": "15min_ohlc_cannot_prove_60s_execution",
    }


__all__ = [
    "BarPriceEnvelope",
    "ClockObservation",
    "ClockSafetyError",
    "ConfirmationProjection",
    "EconomicScore",
    "ExecutionFact",
    "ExecutionToken",
    "ExecutionWindow",
    "FillTimingResult",
    "HoldProjection",
    "RiskBarProjection",
    "SessionRiskPolicy",
    "SessionRiskProjection",
    "ScopedClock",
    "TimingContractError",
    "TokenProjection",
    "calculate_economic_scores",
    "classify_bar_only_fill",
    "classify_execution_facts",
    "compute_bar_envelope",
    "economic_scores",
    "execution_price_allowed",
    "freeze_bar_envelopes",
    "freeze_price_envelopes",
    "price_allowed",
    "project_risk_bar",
    "replay_fill_status",
]
