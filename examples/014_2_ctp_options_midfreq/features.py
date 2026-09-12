"""Pure FQ2 minute quote features for the local Iteration 24 example.

The module consumes an already frozen :class:`MinuteDecisionInput`.  It does
not create a clock mapping, fill missing identity fields, query an account, or
retain a mutable latest quote.  The replay producer lives in ``fq2_fixture``;
this file is deliberately a stateless feature boundary.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
import math
from types import MappingProxyType
from typing import Any, Dict, Iterable, Optional, Tuple

from backtrader.feeds import CtpQuoteEvidence, MinuteDecisionInput


class FeatureReason:
    """Stable reasons emitted by the FQ2 feature boundary."""

    READY = "READY"
    FEATURE_INPUT_INVALID = "FEATURE_INPUT_INVALID"
    FEATURE_SCOPE_MISMATCH = "FEATURE_SCOPE_MISMATCH"
    FEATURE_QUOTE_SCHEMA = "FEATURE_QUOTE_SCHEMA"
    FEATURE_QUOTE_IDENTITY = "FEATURE_QUOTE_IDENTITY"
    FEATURE_QUOTE_FUTURE = "FEATURE_QUOTE_FUTURE"
    FEATURE_QUOTE_LATE = "FEATURE_QUOTE_LATE"
    FEATURE_QUOTE_DUPLICATE = "FEATURE_QUOTE_DUPLICATE"
    FEATURE_QUOTE_CAPACITY = "FEATURE_QUOTE_CAPACITY"
    FEATURE_WINDOW_GAP = "FEATURE_WINDOW_GAP"
    FEATURE_SEGMENT_TOO_LONG = "FEATURE_SEGMENT_TOO_LONG"
    FEATURE_CROSS_LEG_SKEW = "BLOCKED_CROSS_LEG_SKEW"
    BLOCKED_WARMUP = "BLOCKED_WARMUP"
    BLOCKED_SHORT_WINDOW = "BLOCKED_SHORT_WINDOW"
    BLOCKED_LONG_WINDOW = "BLOCKED_LONG_WINDOW"
    BLOCKED_FRESH_STATES = "BLOCKED_FRESH_STATES"
    BLOCKED_PERSISTENCE = "BLOCKED_PERSISTENCE"
    BLOCKED_ADVERSE_PRESSURE = "BLOCKED_ADVERSE_PRESSURE"
    BLOCKED_EXECUTABLE_SIZE = "BLOCKED_EXECUTABLE_SIZE"
    NO_SIGNAL = "NO_SIGNAL"
    NO_SIGNAL_NET_EDGE = "NO_SIGNAL_NET_EDGE"
    NO_SIGNAL_DIRECTION = "NO_SIGNAL_DIRECTION"
    DIRECTION_CONFLICT = "DIRECTION_CONFLICT"


UTC = timezone.utc
_ZERO = Decimal("0")
_ONE = Decimal("1")
_THOUSAND = Decimal("1000")
_MAX_ABS = Decimal("1e30")


def _finite_decimal(value: Any, field: str) -> Decimal:
    if isinstance(value, bool):
        raise ValueError(f"{field} must be numeric")
    try:
        parsed = value if isinstance(value, Decimal) else Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError) as error:
        raise ValueError(f"{field} must be numeric") from error
    if not parsed.is_finite() or abs(parsed) >= _MAX_ABS:
        raise ValueError(f"{field} must be finite")
    return parsed


def _positive_decimal(value: Any, field: str) -> Decimal:
    parsed = _finite_decimal(value, field)
    if parsed <= _ZERO:
        raise ValueError(f"{field} must be positive")
    return parsed


def _aware_datetime(value: Any, field: str) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field} must be timezone-aware")
    return value.astimezone(UTC)


def _datetime_value(event: Any, *names: str) -> Optional[datetime]:
    for name in names:
        if isinstance(event, Mapping) and name in event:
            value = event[name]
        elif not isinstance(event, Mapping) and hasattr(event, name):
            value = getattr(event, name)
        else:
            continue
        if isinstance(value, datetime):
            return _aware_datetime(value, name)
        if isinstance(value, str):
            try:
                return _aware_datetime(datetime.fromisoformat(value.replace("Z", "+00:00")), name)
            except ValueError:
                return None
        return None
    return None


def _value(event: Any, *names: str) -> Any:
    for name in names:
        if isinstance(event, Mapping) and name in event:
            return event[name]
        if not isinstance(event, Mapping) and hasattr(event, name):
            return getattr(event, name)
    return None


def _clock_seconds(data: Mapping[str, Any], *, decision_input: MinuteDecisionInput) -> float:
    """Require an explicit receive observation and verify it against the mapping."""

    nanoseconds = data.get("received_monotonic_ns", data.get("recv_monotonic_ns"))
    seconds = data.get("received_monotonic", data.get("recv_monotonic"))
    parsed_ns = None
    parsed_seconds = None
    if nanoseconds is not None:
        if type(nanoseconds) is not int or nanoseconds < 0:
            raise ValueError("received_monotonic_ns must be a non-negative integer")
        parsed_ns = nanoseconds / 1_000_000_000.0
    if seconds is not None:
        if isinstance(seconds, bool) or not isinstance(seconds, (int, float)):
            raise ValueError("received_monotonic must be numeric")
        parsed_seconds = float(seconds)
        if not math.isfinite(parsed_seconds) or parsed_seconds < 0:
            raise ValueError("received_monotonic must be finite and non-negative")
    if parsed_ns is None and parsed_seconds is None:
        raise ValueError("receive monotonic evidence is required")
    if (
        parsed_ns is not None
        and parsed_seconds is not None
        and not math.isclose(parsed_ns, parsed_seconds, rel_tol=0.0, abs_tol=1e-12)
    ):
        raise ValueError("conflicting receive monotonic evidence")
    observed = parsed_ns if parsed_ns is not None else parsed_seconds
    assert observed is not None
    decision_input.clock_mapping.validate_pair(data["received_at"], observed)
    return observed


def _epoch_datetime(value: Any, field: str) -> datetime:
    try:
        parsed = float(value)
    except (TypeError, ValueError, OverflowError) as error:
        raise ValueError(f"{field} must be finite") from error
    if not math.isfinite(parsed):
        raise ValueError(f"{field} must be finite")
    return datetime.fromtimestamp(parsed, UTC)


@dataclass(frozen=True)
class FeaturePolicy:
    """Explicit FQ2 timing, statistical, and economic thresholds."""

    symbols: Tuple[str, str, str]
    multiplier: Decimal
    strike: Decimal
    discount_factor: Decimal
    price_tick_by_symbol: Mapping[str, Decimal]
    history_bars: int = 60
    short_window_seconds: Decimal = Decimal("5")
    long_window_seconds: Decimal = Decimal("60")
    max_segment_seconds: Decimal = Decimal("2")
    max_cross_leg_skew_ms: Decimal = Decimal("500")
    minimum_new_snapshots: int = 3
    persistence_ratio: Decimal = Decimal("0.8")
    max_adverse_pressure: Decimal = Decimal("0.5")
    residual_floor_cny: Decimal = Decimal("30")
    z_entry: Decimal = Decimal("2.5")
    minimum_net_edge_cny: Decimal = Decimal("20")
    cost_bound_cny: Decimal = Decimal("20")

    def __post_init__(self) -> None:
        if len(self.symbols) != 3 or len(set(self.symbols)) != 3:
            raise ValueError("symbols must contain three distinct legs")
        if not all(isinstance(symbol, str) and symbol for symbol in self.symbols):
            raise ValueError("symbols must be non-empty strings")
        object.__setattr__(self, "multiplier", _positive_decimal(self.multiplier, "multiplier"))
        object.__setattr__(self, "strike", _finite_decimal(self.strike, "strike"))
        discount = _positive_decimal(self.discount_factor, "discount_factor")
        if discount > _ONE:
            raise ValueError("discount_factor must be at most one")
        object.__setattr__(self, "discount_factor", discount)
        ticks = {
            symbol: _positive_decimal(self.price_tick_by_symbol[symbol], f"price_tick.{symbol}")
            for symbol in self.symbols
        }
        object.__setattr__(self, "price_tick_by_symbol", MappingProxyType(ticks))
        if type(self.history_bars) is not int or self.history_bars <= 0:
            raise ValueError("history_bars must be a positive integer")
        for field in (
            "short_window_seconds",
            "long_window_seconds",
            "max_segment_seconds",
            "max_cross_leg_skew_ms",
            "persistence_ratio",
            "max_adverse_pressure",
            "residual_floor_cny",
            "z_entry",
            "minimum_net_edge_cny",
            "cost_bound_cny",
        ):
            object.__setattr__(self, field, _positive_decimal(getattr(self, field), field))
        if self.long_window_seconds < self.short_window_seconds:
            raise ValueError("long_window_seconds must cover short_window_seconds")
        if self.short_window_seconds != Decimal("5"):
            raise ValueError("short_window_seconds must be exactly five seconds")
        if self.long_window_seconds != Decimal("60"):
            raise ValueError("long_window_seconds must be exactly sixty seconds")
        if self.max_segment_seconds > Decimal("2"):
            raise ValueError("max_segment_seconds may not exceed two seconds")
        if self.max_cross_leg_skew_ms > Decimal("500"):
            raise ValueError("max_cross_leg_skew_ms may not exceed 500ms")
        if not Decimal("0.8") <= self.persistence_ratio <= _ONE:
            raise ValueError("persistence_ratio must be between 0.8 and one")
        if not _ZERO < self.max_adverse_pressure <= Decimal("0.5"):
            raise ValueError("max_adverse_pressure must be positive and at most 0.5")
        if self.minimum_net_edge_cny < Decimal("20"):
            raise ValueError("minimum_net_edge_cny must be at least 20")
        if self.z_entry < Decimal("2.5"):
            raise ValueError("z_entry must be at least 2.5")
        economic_floor = self.multiplier * (
            self.price_tick_by_symbol[self.symbols[0]] * self.discount_factor
            + self.price_tick_by_symbol[self.symbols[1]]
            + self.price_tick_by_symbol[self.symbols[2]]
        )
        if self.residual_floor_cny < economic_floor:
            raise ValueError(
                "residual_floor_cny is below the bound implied by multiplier, discount, and ticks"
            )
        if type(self.minimum_new_snapshots) is not int or self.minimum_new_snapshots < 3:
            raise ValueError("minimum_new_snapshots must be at least three")


@dataclass(frozen=True)
class QuoteSnapshot:
    """A detached, typed quote consumed by the feature integrator."""

    symbol: str
    event_time: datetime
    received_at: datetime
    ingest_seq: int
    bid: Decimal
    ask: Decimal
    bid_qty: Decimal
    ask_qty: Decimal
    generation: int
    trading_day: str
    session_segment: str
    rules_hash: str
    clock_domain: str
    candidate_id: str
    source: str
    event_time_source: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "event_time", _aware_datetime(self.event_time, "event_time"))
        object.__setattr__(self, "received_at", _aware_datetime(self.received_at, "received_at"))
        if type(self.ingest_seq) is not int or self.ingest_seq <= 0:
            raise ValueError("ingest_seq must be a positive integer")
        for field in ("bid", "ask", "bid_qty", "ask_qty"):
            object.__setattr__(self, field, _positive_decimal(getattr(self, field), field))
        if self.ask < self.bid:
            raise ValueError("ask must be at or above bid")
        if type(self.generation) is not int or self.generation <= 0:
            raise ValueError("generation must be a positive integer")
        for field in (
            "symbol",
            "trading_day",
            "session_segment",
            "rules_hash",
            "clock_domain",
            "candidate_id",
            "source",
            "event_time_source",
        ):
            value = getattr(self, field)
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"{field} must be a non-empty string")
        if self.event_time > self.received_at:
            raise ValueError("event_time cannot be after received_at")

    @property
    def mid(self) -> Decimal:
        return (self.bid + self.ask) / Decimal("2")

    @property
    def imbalance(self) -> Decimal:
        return (self.bid_qty - self.ask_qty) / (self.bid_qty + self.ask_qty)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "symbol": self.symbol,
            "event_time": self.event_time.isoformat(),
            "received_at": self.received_at.isoformat(),
            "ingest_seq": self.ingest_seq,
            "bid": float(self.bid),
            "ask": float(self.ask),
            "bid_qty": float(self.bid_qty),
            "ask_qty": float(self.ask_qty),
            "generation": self.generation,
            "trading_day": self.trading_day,
            "session_segment": self.session_segment,
            "rules_hash": self.rules_hash,
            "clock_domain": self.clock_domain,
            "candidate_id": self.candidate_id,
        }


def _typed_quote_to_mapping(
    event: CtpQuoteEvidence,
    *,
    session_segment: Optional[str] = None,
    candidate_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Adapt one already validated CTP quote without dropping its fields.

    ``CtpQuoteEvidence`` deliberately carries connection identity but does not
    carry the strategy candidate or the session label.  Those two values are
    supplied by the frozen minute scope when a typed quote is consumed.  The
    caller therefore has to provide them; the feature layer never invents a
    scope for a quote.
    """

    if not isinstance(session_segment, str) or not session_segment:
        raise ValueError("typed quote session_segment is required")
    if not isinstance(candidate_id, str) or not candidate_id:
        raise ValueError("typed quote candidate_id is required")
    return {
        "symbol": event.symbol,
        "exchange": event.exchange,
        "event_time": _epoch_datetime(event.source_epoch, "source_epoch"),
        "received_at": _epoch_datetime(event.receive_epoch, "receive_epoch"),
        "received_monotonic_ns": event.receive_monotonic_ns,
        "ingest_seq": event.ingest_seq,
        "generation": event.connection_generation,
        "trading_day": event.trading_day,
        "session_segment": session_segment,
        "rules_hash": event.rules_hash,
        "clock_domain": event.clock_domain_id,
        "candidate_id": candidate_id,
        "source": event.source,
        "event_time_source": event.event_time_source,
        "quality": "GOOD",
        "volume_complete": True,
        "bid": event.bid,
        "ask": event.ask,
        "bid_qty": event.bid_size,
        "ask_qty": event.ask_size,
    }


def _normalize_quote(
    event: Any,
    *,
    symbol: str,
    session_segment: Optional[str] = None,
    candidate_id: Optional[str] = None,
) -> QuoteSnapshot:
    if isinstance(event, CtpQuoteEvidence):
        data = _typed_quote_to_mapping(
            event, session_segment=session_segment, candidate_id=candidate_id
        )
    elif isinstance(event, Mapping):
        data = dict(event)
    else:
        raise ValueError("quote must be a mapping or CtpQuoteEvidence")
    event_time = _datetime_value(data, "event_time", "event_time_utc", "source_time")
    receive_time = _datetime_value(data, "received_at", "recv_time_utc", "received_wall_time")
    if event_time is None or receive_time is None:
        raise ValueError("quote event and receive timestamps are required")
    if _value(data, "quality") != "GOOD" or _value(data, "volume_complete") is not True:
        raise ValueError("quote quality and volume completeness must be explicit")
    values = {
        "symbol": _value(data, "symbol", "instrument_id"),
        "event_time": event_time,
        "received_at": receive_time,
        "ingest_seq": _value(data, "ingest_seq", "sequence"),
        "bid": _value(data, "bid", "bid_price", "BidPrice1"),
        "ask": _value(data, "ask", "ask_price", "AskPrice1"),
        "bid_qty": _value(data, "bid_qty", "bid_size", "bid_volume", "BidVolume1"),
        "ask_qty": _value(data, "ask_qty", "ask_size", "ask_volume", "AskVolume1"),
        "generation": _value(data, "generation", "connection_generation"),
        "trading_day": _value(data, "trading_day", "TradingDay"),
        "session_segment": _value(data, "session_segment", "session"),
        "rules_hash": _value(data, "rules_hash"),
        "clock_domain": _value(data, "clock_domain", "clock_domain_id"),
        "candidate_id": _value(data, "candidate_id"),
        "source": _value(data, "source"),
        "event_time_source": _value(data, "event_time_source"),
    }
    if values["symbol"] != symbol:
        raise ValueError("quote symbol does not match expected leg")
    return QuoteSnapshot(**values)


def _median(values: Sequence[Decimal]) -> Decimal:
    if not values:
        raise ValueError("median requires values")
    ordered = sorted(values)
    middle = len(ordered) // 2
    if len(ordered) % 2:
        return ordered[middle]
    return (ordered[middle - 1] + ordered[middle]) / Decimal("2")


@dataclass(frozen=True)
class _WindowStats:
    covered_ms: int
    complete: bool
    i5_by_symbol: Mapping[str, Decimal]
    persistence_ms: Mapping[str, int]
    synchronized_states: int
    max_source_skew_ms: Decimal
    max_receive_skew_ms: Decimal
    reason: Optional[str]


def _latest_at(events: Sequence[QuoteSnapshot], at: datetime) -> Optional[QuoteSnapshot]:
    """Return the latest quote known by the receive-time as-of boundary.

    Source event time remains the quote's age/skew clock, while receive time
    controls when that quote can affect a frozen calculation.  Sorting by
    receive time first prevents a late source timestamp from backfilling an
    earlier interval; ingest sequence breaks ties for simultaneous receives.
    """

    candidates = [event for event in events if event.received_at <= at]
    if not candidates:
        return None
    return max(candidates, key=lambda event: (event.received_at, event.ingest_seq))


def _window_stats(
    quotes: Mapping[str, Sequence[QuoteSnapshot]],
    *,
    start: datetime,
    end: datetime,
    policy: FeaturePolicy,
) -> _WindowStats:
    boundaries = {start, end}
    for events in quotes.values():
        boundaries.update(event.received_at for event in events if start <= event.received_at < end)
    ordered = sorted(boundaries)
    integrals = dict.fromkeys(policy.symbols, _ZERO)
    persistence = {"conversion": 0, "reversal": 0}
    covered_ms = 0
    states = set()
    max_source_skew = _ZERO
    max_receive_skew = _ZERO
    reason = None
    max_age = timedelta(seconds=float(policy.max_segment_seconds))
    for left, right in zip(ordered, ordered[1:]):
        if right <= left:
            continue
        current = {symbol: _latest_at(quotes[symbol], left) for symbol in policy.symbols}
        duration_ms = int(round((right - left).total_seconds() * 1000.0))
        if any(event is None for event in current.values()):
            reason = reason or FeatureReason.FEATURE_WINDOW_GAP
            continue
        events = tuple(current[symbol] for symbol in policy.symbols)
        assert all(event is not None for event in events)
        stale_at = min(event.event_time + max_age for event in events)
        valid_right = min(right, stale_at)
        valid_ms = int(round(max(0.0, (valid_right - left).total_seconds() * 1000.0)))
        if valid_ms <= 0:
            reason = reason or FeatureReason.FEATURE_WINDOW_GAP
            continue
        if valid_ms < duration_ms:
            reason = reason or FeatureReason.FEATURE_SEGMENT_TOO_LONG
        source_skew = Decimal(
            str(
                (
                    max(event.event_time for event in events)
                    - min(event.event_time for event in events)
                ).total_seconds()
                * 1000.0
            )
        )
        receive_skew = Decimal(
            str(
                (
                    max(event.received_at for event in events)
                    - min(event.received_at for event in events)
                ).total_seconds()
                * 1000.0
            )
        )
        max_source_skew = max(max_source_skew, source_skew)
        max_receive_skew = max(max_receive_skew, receive_skew)
        if (
            source_skew > policy.max_cross_leg_skew_ms
            or receive_skew > policy.max_cross_leg_skew_ms
        ):
            reason = reason or FeatureReason.FEATURE_CROSS_LEG_SKEW
            continue
        covered_ms += valid_ms
        # A carry-in quote may provide the first interval's valid price, but
        # it is not a fresh synchronized state for the FQ2 minimum.  A state
        # becomes new only when the latest selected leg was received inside
        # this window.  Duplicate callbacks are removed before this point by
        # ingest sequence, while a new sequence at the same source timestamp
        # remains a new receive-time observation.
        state_identity = tuple(event.ingest_seq for event in events)
        state_introduced_at = max(event.received_at for event in events)
        if state_introduced_at >= start:
            states.add(state_identity)
        fraction = Decimal(valid_ms) / Decimal("1000")
        for symbol, event in zip(policy.symbols, events):
            integrals[symbol] += event.imbalance * fraction
        conversion_score = _score(events, policy, "conversion")
        reversal_score = _score(events, policy, "reversal")
        if conversion_score > policy.minimum_net_edge_cny:
            persistence["conversion"] += valid_ms
        if reversal_score > policy.minimum_net_edge_cny:
            persistence["reversal"] += valid_ms
        del duration_ms
    window_ms = int(round((end - start).total_seconds() * 1000.0))
    complete = covered_ms == window_ms and reason is None
    denominator = Decimal(window_ms) / Decimal("1000")
    i5 = {symbol: integrals[symbol] / denominator for symbol in policy.symbols}
    # Persistence is always measured against the complete 5-second wall
    # window.  Missing time therefore lowers P; it cannot be treated as zero
    # score or silently removed from the denominator.
    return _WindowStats(
        covered_ms=covered_ms,
        complete=complete,
        i5_by_symbol=MappingProxyType(i5),
        persistence_ms=MappingProxyType(dict(persistence)),
        synchronized_states=len(states),
        max_source_skew_ms=max_source_skew,
        max_receive_skew_ms=max_receive_skew,
        reason=reason,
    )


def _score(events: Sequence[QuoteSnapshot], policy: FeaturePolicy, direction: str) -> Decimal:
    by_symbol = {event.symbol: event for event in events}
    future, call, put = (by_symbol[symbol] for symbol in policy.symbols)
    if direction == "conversion":
        gross = policy.multiplier * (
            call.bid - put.ask - policy.discount_factor * (future.ask - policy.strike)
        )
    else:
        gross = policy.multiplier * (
            put.bid - call.ask + policy.discount_factor * (future.bid - policy.strike)
        )
    return gross - policy.cost_bound_cny


def _validate_input(
    decision_input: MinuteDecisionInput, policy: FeaturePolicy
) -> Tuple[Dict[str, Tuple[QuoteSnapshot, ...]], Tuple[str, ...]]:
    if not isinstance(decision_input, MinuteDecisionInput):
        return {}, (FeatureReason.FEATURE_INPUT_INVALID,)
    try:
        start = _aware_datetime(decision_input.bucket_start, "bucket_start")
        end = _aware_datetime(decision_input.bucket_end, "bucket_end")
        if end <= start:
            raise ValueError("bucket must be increasing")
        if decision_input.generation <= 0 or decision_input.clock_mode != "replay":
            raise ValueError("unsupported input scope")
        if tuple(decision_input.bars) != policy.symbols:
            raise ValueError("bar symbols do not match feature policy")
        if any(decision_input.bars[symbol].symbol != symbol for symbol in policy.symbols):
            raise ValueError("bar symbol mismatch")
    except (AttributeError, TypeError, ValueError):
        return {}, (FeatureReason.FEATURE_SCOPE_MISMATCH,)

    quotes: Dict[str, Tuple[QuoteSnapshot, ...]] = {}
    reasons = []
    total = 0
    for symbol in policy.symbols:
        bar = decision_input.bars[symbol]
        raw_events = decision_input.accepted_quotes.get(symbol, ())
        if not isinstance(raw_events, (tuple, list)):
            reasons.append(FeatureReason.FEATURE_QUOTE_SCHEMA)
            continue
        if decision_input.quote_rejections.get(symbol):
            reasons.append(FeatureReason.FEATURE_QUOTE_SCHEMA)
        if len(raw_events) > 256:
            reasons.append(FeatureReason.FEATURE_QUOTE_CAPACITY)
            continue
        normalized = []
        seen = set()
        for raw in raw_events:
            try:
                raw_data = dict(raw) if isinstance(raw, Mapping) else {}
                if isinstance(raw, CtpQuoteEvidence):
                    raw_data = _typed_quote_to_mapping(
                        raw,
                        session_segment=decision_input.session_segment,
                        candidate_id=decision_input.candidate_id,
                    )
                raw_exchange = _value(raw_data, "exchange", "exchange_id", "ExchangeID")
                if raw_exchange != bar.exchange:
                    reasons.append(FeatureReason.FEATURE_QUOTE_IDENTITY)
                    continue
                raw_mode = _value(raw_data, "clock_mode")
                if raw_mode != decision_input.clock_mode:
                    reasons.append(FeatureReason.FEATURE_QUOTE_IDENTITY)
                    continue
                raw_data["received_at"] = _datetime_value(
                    raw_data, "received_at", "recv_time_utc", "received_wall_time"
                )
                if raw_data["received_at"] is None:
                    raise ValueError("quote receive timestamp is required")
                _clock_seconds(raw_data, decision_input=decision_input)
                event = _normalize_quote(
                    raw_data,
                    symbol=symbol,
                    session_segment=decision_input.session_segment,
                    candidate_id=decision_input.candidate_id,
                )
                if event.ingest_seq in seen:
                    reasons.append(FeatureReason.FEATURE_QUOTE_DUPLICATE)
                    continue
                seen.add(event.ingest_seq)
                if event.event_time >= end:
                    reasons.append(FeatureReason.FEATURE_QUOTE_FUTURE)
                    continue
                if event.received_at > bar.seal_received_at:
                    reasons.append(FeatureReason.FEATURE_QUOTE_LATE)
                    continue
                if event.ingest_seq > bar.quote_cutoff_seq:
                    reasons.append(FeatureReason.FEATURE_QUOTE_LATE)
                    continue
                expected = {
                    "generation": decision_input.generation,
                    "trading_day": decision_input.trading_day,
                    "session_segment": decision_input.session_segment,
                    "rules_hash": decision_input.rules_hash,
                    "clock_domain": decision_input.clock_domain,
                    "candidate_id": decision_input.candidate_id,
                }
                actual = {
                    "generation": event.generation,
                    "trading_day": event.trading_day,
                    "session_segment": event.session_segment,
                    "rules_hash": event.rules_hash,
                    "clock_domain": event.clock_domain,
                    "candidate_id": event.candidate_id,
                }
                if actual != expected:
                    reasons.append(FeatureReason.FEATURE_QUOTE_IDENTITY)
                    continue
                if event.received_at < decision_input.bucket_start - timedelta(seconds=60):
                    reasons.append(FeatureReason.FEATURE_QUOTE_LATE)
                    continue
                normalized.append(event)
            except (TypeError, ValueError, KeyError):
                reasons.append(FeatureReason.FEATURE_QUOTE_SCHEMA)
        normalized.sort(key=lambda event: (event.event_time, event.ingest_seq))
        quotes[symbol] = tuple(normalized)
        total += len(normalized)
    if total > 768:
        reasons.append(FeatureReason.FEATURE_QUOTE_CAPACITY)
    return quotes, tuple(dict.fromkeys(reasons))


@dataclass(frozen=True)
class MinuteFeatures:
    """Immutable result of one closed minute's FQ2 computation."""

    bucket_end: datetime
    candidate_id: str
    bar_ids: Tuple[str, ...]
    quote_cutoffs: Mapping[str, int]
    generation: int
    rules_hash: str
    history_before_current: int
    residual_cny: Decimal
    i5_by_symbol: Mapping[str, Decimal]
    microprice_by_symbol: Mapping[str, Decimal]
    micro_shift_ticks_by_symbol: Mapping[str, Decimal]
    adverse_pressure_conversion: Decimal
    adverse_pressure_reversal: Decimal
    score_conversion_cny: Decimal
    score_reversal_cny: Decimal
    persistence_conversion: Decimal
    persistence_reversal: Decimal
    short_window_covered_ms: int
    long_window_covered_ms: int
    short_window_complete: bool
    long_window_complete: bool
    synchronized_states_5s: int
    source_skew_ms: Decimal
    receive_skew_ms: Decimal
    median_cny: Optional[Decimal]
    mad_cny: Optional[Decimal]
    scale_cny: Optional[Decimal]
    z_score: Optional[Decimal]
    direction: Optional[str]
    signal_ready: bool
    reason: str
    reasons: Tuple[str, ...] = ()

    @property
    def tradable(self) -> bool:
        return self.signal_ready

    def to_dict(self) -> Dict[str, Any]:
        def number(value: Optional[Decimal]) -> Optional[float]:
            return None if value is None else float(value)

        return {
            "bucket_end": self.bucket_end.isoformat(),
            "candidate_id": self.candidate_id,
            "bar_ids": list(self.bar_ids),
            "quote_cutoffs": dict(self.quote_cutoffs),
            "generation": self.generation,
            "rules_hash": self.rules_hash,
            "history_before_current": self.history_before_current,
            "residual_cny": float(self.residual_cny),
            "i5_by_symbol": {key: float(value) for key, value in self.i5_by_symbol.items()},
            "microprice_by_symbol": {
                key: float(value) for key, value in self.microprice_by_symbol.items()
            },
            "micro_shift_ticks_by_symbol": {
                key: float(value) for key, value in self.micro_shift_ticks_by_symbol.items()
            },
            "adverse_pressure_conversion": float(self.adverse_pressure_conversion),
            "adverse_pressure_reversal": float(self.adverse_pressure_reversal),
            "score_conversion_cny": float(self.score_conversion_cny),
            "score_reversal_cny": float(self.score_reversal_cny),
            "persistence_conversion": float(self.persistence_conversion),
            "persistence_reversal": float(self.persistence_reversal),
            "short_window_covered_ms": self.short_window_covered_ms,
            "long_window_covered_ms": self.long_window_covered_ms,
            "short_window_complete": self.short_window_complete,
            "long_window_complete": self.long_window_complete,
            "synchronized_states_5s": self.synchronized_states_5s,
            "source_skew_ms": float(self.source_skew_ms),
            "receive_skew_ms": float(self.receive_skew_ms),
            "median_cny": number(self.median_cny),
            "mad_cny": number(self.mad_cny),
            "scale_cny": number(self.scale_cny),
            "z_score": number(self.z_score),
            "direction": self.direction,
            "signal_ready": self.signal_ready,
            "reason": self.reason,
            "reasons": list(self.reasons),
        }


def _empty_features(
    decision_input: MinuteDecisionInput,
    *,
    history_before_current: int,
    reason: str,
    reasons: Iterable[str] = (),
) -> MinuteFeatures:
    symbols = tuple(decision_input.bars)
    zeros = MappingProxyType(dict.fromkeys(symbols, _ZERO))
    return MinuteFeatures(
        bucket_end=decision_input.bucket_end,
        candidate_id=decision_input.candidate_id,
        bar_ids=tuple(decision_input.bar_ids),
        quote_cutoffs=MappingProxyType(dict(decision_input.quote_cutoffs)),
        generation=decision_input.generation,
        rules_hash=decision_input.rules_hash,
        history_before_current=history_before_current,
        residual_cny=_ZERO,
        i5_by_symbol=zeros,
        microprice_by_symbol=zeros,
        micro_shift_ticks_by_symbol=zeros,
        adverse_pressure_conversion=_ZERO,
        adverse_pressure_reversal=_ZERO,
        score_conversion_cny=_ZERO,
        score_reversal_cny=_ZERO,
        persistence_conversion=_ZERO,
        persistence_reversal=_ZERO,
        short_window_covered_ms=0,
        long_window_covered_ms=0,
        short_window_complete=False,
        long_window_complete=False,
        synchronized_states_5s=0,
        source_skew_ms=_ZERO,
        receive_skew_ms=_ZERO,
        median_cny=None,
        mad_cny=None,
        scale_cny=None,
        z_score=None,
        direction=None,
        signal_ready=False,
        reason=reason,
        reasons=tuple(dict.fromkeys(reasons)),
    )


def compute_minute_features(
    decision_input: MinuteDecisionInput,
    *,
    policy: FeaturePolicy,
    history: Sequence[Decimal],
) -> MinuteFeatures:
    """Compute one closed-minute feature snapshot from frozen quote evidence.

    ``history`` contains only prior valid minutes.  The current residual is
    never used to calculate its own median/MAD and is returned for the caller
    to append after this function completes.
    """

    history_before_current = len(history)
    quotes, input_reasons = _validate_input(decision_input, policy)
    if input_reasons:
        return _empty_features(
            decision_input,
            history_before_current=history_before_current,
            reason=input_reasons[0],
            reasons=input_reasons,
        )
    try:
        end = _aware_datetime(decision_input.bucket_end, "bucket_end")
        latest = {
            symbol: _latest_at(quotes[symbol], end - timedelta(microseconds=1))
            for symbol in policy.symbols
        }
        if any(event is None for event in latest.values()):
            return _empty_features(
                decision_input,
                history_before_current=history_before_current,
                reason=FeatureReason.FEATURE_WINDOW_GAP,
                reasons=(FeatureReason.FEATURE_WINDOW_GAP,),
            )
        latest_events = tuple(latest[symbol] for symbol in policy.symbols)
        assert all(event is not None for event in latest_events)
        latest_source_skew = Decimal(
            str(
                (
                    max(event.event_time for event in latest_events)
                    - min(event.event_time for event in latest_events)
                ).total_seconds()
                * 1000.0
            )
        )
        latest_receive_skew = Decimal(
            str(
                (
                    max(event.received_at for event in latest_events)
                    - min(event.received_at for event in latest_events)
                ).total_seconds()
                * 1000.0
            )
        )
        short_start = end - timedelta(seconds=float(policy.short_window_seconds))
        long_start = end - timedelta(seconds=float(policy.long_window_seconds))
        short = _window_stats(quotes, start=short_start, end=end, policy=policy)
        long = _window_stats(quotes, start=long_start, end=end, policy=policy)
        source_skew = max(short.max_source_skew_ms, long.max_source_skew_ms, latest_source_skew)
        receive_skew = max(short.max_receive_skew_ms, long.max_receive_skew_ms, latest_receive_skew)
        by_symbol = {event.symbol: event for event in latest_events}
        future, call, put = (by_symbol[symbol] for symbol in policy.symbols)
        residual = policy.multiplier * (
            call.mid - put.mid - policy.discount_factor * (future.mid - policy.strike)
        )
        microprice = {
            symbol: (event.ask * event.bid_qty + event.bid * event.ask_qty)
            / (event.bid_qty + event.ask_qty)
            for symbol, event in by_symbol.items()
        }
        shifts = {
            symbol: (microprice[symbol] - event.mid) / policy.price_tick_by_symbol[symbol]
            for symbol, event in by_symbol.items()
        }
        i5 = short.i5_by_symbol
        adverse_conversion = (
            i5[policy.symbols[0]] + i5[policy.symbols[2]] - i5[policy.symbols[1]]
        ) / Decimal("3")
        adverse_reversal = -adverse_conversion
        score_conversion = _score(latest_events, policy, "conversion")
        score_reversal = _score(latest_events, policy, "reversal")
    except (TypeError, ValueError, KeyError, ArithmeticError):
        return _empty_features(
            decision_input,
            history_before_current=history_before_current,
            reason=FeatureReason.FEATURE_INPUT_INVALID,
            reasons=(FeatureReason.FEATURE_INPUT_INVALID,),
        )

    center = mad = scale = z_score = None
    if history_before_current >= policy.history_bars:
        historical = tuple(_finite_decimal(value, "history") for value in history)
        if len(historical) < policy.history_bars:
            history_before_current = len(historical)
        else:
            historical = historical[-policy.history_bars :]
            center = _median(historical)
            mad = _median(tuple(abs(value - center) for value in historical))
            scale = max(Decimal("1.4826") * mad, policy.residual_floor_cny)
            z_score = (residual - center) / scale

    reasons = list(input_reasons)
    if long.reason is not None:
        reasons.append(long.reason)
    if short.reason is not None:
        reasons.append(short.reason)
    if not long.complete:
        reasons.append(FeatureReason.BLOCKED_LONG_WINDOW)
    if not short.complete:
        reasons.append(FeatureReason.BLOCKED_SHORT_WINDOW)
    if short.synchronized_states < policy.minimum_new_snapshots:
        reasons.append(FeatureReason.BLOCKED_FRESH_STATES)
    short_window_ms = int(round(float(policy.short_window_seconds) * 1000.0))
    p_conversion = Decimal(short.persistence_ms["conversion"]) / Decimal(short_window_ms)
    p_reversal = Decimal(short.persistence_ms["reversal"]) / Decimal(short_window_ms)
    # Keep a diagnostic blocker only when both directions fail the persistence
    # gate.  A valid conversion signal must not be reported with the
    # reversal-only blocker attached (and vice versa); the selected direction
    # is the economic decision being consumed by the strategy.
    if p_conversion < policy.persistence_ratio and p_reversal < policy.persistence_ratio:
        reasons.append(FeatureReason.BLOCKED_PERSISTENCE)
    if (
        adverse_conversion > policy.max_adverse_pressure
        and adverse_reversal > policy.max_adverse_pressure
    ):
        reasons.append(FeatureReason.BLOCKED_ADVERSE_PRESSURE)
    if history_before_current < policy.history_bars or z_score is None:
        reasons.append(FeatureReason.BLOCKED_WARMUP)

    executable = all(event.bid_qty >= _ONE and event.ask_qty >= _ONE for event in latest_events)
    if not executable:
        reasons.append(FeatureReason.BLOCKED_EXECUTABLE_SIZE)
    common_tick_gate = (
        short.complete
        and long.complete
        and short.synchronized_states >= policy.minimum_new_snapshots
        and source_skew <= policy.max_cross_leg_skew_ms
        and receive_skew <= policy.max_cross_leg_skew_ms
        and executable
    )
    conversion_tick_gate = (
        common_tick_gate
        and p_conversion >= policy.persistence_ratio
        and adverse_conversion <= policy.max_adverse_pressure
    )
    reversal_tick_gate = (
        common_tick_gate
        and p_reversal >= policy.persistence_ratio
        and adverse_reversal <= policy.max_adverse_pressure
    )
    conversion_direction = (
        residual > _ZERO
        and z_score is not None
        and z_score >= policy.z_entry
        and score_conversion > policy.minimum_net_edge_cny
        and conversion_tick_gate
    )
    reversal_direction = (
        residual < _ZERO
        and z_score is not None
        and z_score <= -policy.z_entry
        and score_reversal > policy.minimum_net_edge_cny
        and reversal_tick_gate
    )
    direction = None
    signal_ready = False
    reason = FeatureReason.READY
    if conversion_direction and reversal_direction:
        reason = FeatureReason.DIRECTION_CONFLICT
        reasons.append(reason)
    elif conversion_direction:
        direction = "conversion"
        signal_ready = True
    elif reversal_direction:
        direction = "reversal"
        signal_ready = True
    elif z_score is not None and (
        (residual > _ZERO and z_score >= policy.z_entry)
        or (residual < _ZERO and z_score <= -policy.z_entry)
    ):
        reason = FeatureReason.NO_SIGNAL_NET_EDGE
        reasons.append(reason)
    elif history_before_current < policy.history_bars:
        reason = FeatureReason.BLOCKED_WARMUP
    elif not common_tick_gate:
        reason = reasons[0] if reasons else FeatureReason.BLOCKED_SHORT_WINDOW
    else:
        reason = FeatureReason.NO_SIGNAL
        reasons.append(reason)

    return MinuteFeatures(
        bucket_end=end,
        candidate_id=decision_input.candidate_id,
        bar_ids=tuple(decision_input.bar_ids),
        quote_cutoffs=MappingProxyType(dict(decision_input.quote_cutoffs)),
        generation=decision_input.generation,
        rules_hash=decision_input.rules_hash,
        history_before_current=history_before_current,
        residual_cny=residual,
        i5_by_symbol=MappingProxyType(dict(i5)),
        microprice_by_symbol=MappingProxyType(dict(microprice)),
        micro_shift_ticks_by_symbol=MappingProxyType(dict(shifts)),
        adverse_pressure_conversion=adverse_conversion,
        adverse_pressure_reversal=adverse_reversal,
        score_conversion_cny=score_conversion,
        score_reversal_cny=score_reversal,
        persistence_conversion=p_conversion,
        persistence_reversal=p_reversal,
        short_window_covered_ms=short.covered_ms,
        long_window_covered_ms=long.covered_ms,
        short_window_complete=short.complete,
        long_window_complete=long.complete,
        synchronized_states_5s=short.synchronized_states,
        source_skew_ms=source_skew,
        receive_skew_ms=receive_skew,
        median_cny=center,
        mad_cny=mad,
        scale_cny=scale,
        z_score=z_score,
        direction=direction,
        signal_ready=signal_ready,
        reason=reason,
        reasons=tuple(dict.fromkeys(reasons)),
    )


__all__ = [
    "FeaturePolicy",
    "FeatureReason",
    "MinuteFeatures",
    "QuoteSnapshot",
    "compute_minute_features",
]
