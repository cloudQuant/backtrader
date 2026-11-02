"""Causal level-one quote features for the SA v0 candidate.

Provider ticks and replay fixture ticks use separate SDK schemas and sequence
namespaces. Replay event time supports deterministic feature calculation, but
does not provide a receive clock, freshness, or execution eligibility.
"""

from __future__ import annotations

import math
from datetime import datetime, timezone
from collections import deque
from dataclasses import asdict, dataclass
from typing import Any, Deque, Iterable, Optional

MAX_MARKET_VALUE_ABS = 1.0e30


def _value(source: Any, *names: str, default: Any = None) -> Any:
    if isinstance(source, dict):
        for name in names:
            if source.get(name) is not None:
                return source[name]
        return default
    for name in names:
        value = getattr(source, name, None)
        if value is not None:
            return value
    return default


def _present(source: Any, *names: str) -> bool:
    """Return whether at least one named field is explicitly present.

    ``_value`` is deliberately permissive for optional provider fields. Each
    SDK schema checks its own required set before accepting a quote.
    """

    if isinstance(source, dict):
        return any(name in source for name in names)
    missing = object()
    return any(getattr(source, name, missing) is not missing for name in names)


def _finite(value: Any) -> bool:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return False
    return math.isfinite(number) and abs(number) < MAX_MARKET_VALUE_ABS


def _epoch(value: Any) -> Optional[float]:
    if isinstance(value, datetime):
        moment = value if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)
        return moment.astimezone(timezone.utc).timestamp()
    if isinstance(value, str):
        try:
            moment = datetime.fromisoformat(value.replace("Z", "+00:00"))
            if moment.tzinfo is None:
                moment = moment.replace(tzinfo=timezone.utc)
            return moment.astimezone(timezone.utc).timestamp()
        except ValueError:
            try:
                value = float(value)
            except ValueError:
                return None
    if not _finite(value):
        return None
    result = float(value)
    if result > 10_000_000_000:
        result /= 1000.0
    return result


def _on_tick_grid(value: float, tick_size: float, tolerance: float = 1.0e-8) -> bool:
    units = value / tick_size
    return abs(units - round(units)) <= tolerance


@dataclass(frozen=True)
class QuoteSnapshot:
    """Normalized provider quote or explicitly lineage-bound replay quote."""

    event_time: float
    recv_monotonic: Optional[float]
    ingest_seq: Optional[int]
    bid: float
    ask: float
    bid_size: float
    ask_size: float
    last: float
    cum_volume: Optional[float]
    delta_volume: Optional[float]
    open_interest: float
    lower_limit: float
    upper_limit: float
    trading_day: str
    event_session_date: str
    generation: Optional[int]
    source: str
    schema_version: str = ""
    recv_time_utc: Optional[float] = None
    volume_quality: str = ""
    event_time_source: str = ""
    continuity_status: str = ""
    volume_complete: bool = False
    source_mode: str = "provider"
    replay_source_ref: str = ""
    replay_epoch: str = ""
    replay_sequence: Optional[int] = None

    @property
    def sequence(self) -> Optional[int]:
        """Return the sequence in its own provider or replay namespace."""
        return self.replay_sequence if self.source_mode in {"replay", "synthetic"} else self.ingest_seq

    @property
    def mid(self) -> float:
        """Return the bid/ask midpoint."""
        return (self.bid + self.ask) / 2.0

    @property
    def imbalance(self) -> float:
        """Return the signed level-one depth imbalance."""
        return (self.bid_size - self.ask_size) / (self.bid_size + self.ask_size)

    @property
    def microprice(self) -> float:
        """Return the size-weighted level-one microprice."""
        depth = self.bid_size + self.ask_size
        return (self.ask * self.bid_size + self.bid * self.ask_size) / depth


@dataclass(frozen=True)
class QuoteValidation:
    """Outcome of normalizing one raw quote event, carrying the snapshot when valid."""

    valid: bool
    reason: str
    quote: Optional[QuoteSnapshot] = None


def _day_text(value: Any) -> str:
    """Normalize a provider-neutral date without interpreting provider fields."""
    if hasattr(value, "isoformat") and not isinstance(value, str):
        value = value.isoformat()
    text = str(value or "").strip()
    if len(text) == 10 and text[4] == "-" and text[7] == "-":
        return text.replace("-", "")
    return text


def normalize_quote(
    raw: Any,
    *,
    tick_size: float,
    now_wall_utc: Optional[float] = None,
    now_monotonic: Optional[float] = None,
    max_receive_age: float = 2.0,
    max_event_age: float = 2.0,
) -> QuoteValidation:
    """Normalize only the SDK provider tick and SDK replay tick contracts.

    Replay has event-time lineage but no receive clock, freshness claim,
    provider generation, or ingest sequence. Its sequence stays in the separate
    replay namespace and never participates in live clock validation.
    """
    if not _finite(tick_size) or float(tick_size) <= 0:
        return QuoteValidation(False, "invalid_tick_size")
    schema_version = str(_value(raw, "schema_version", default="") or "")
    live_schema = schema_version == "sdk.market.tick.v1"
    replay_schema = schema_version == "sdk.replay.market.tick.v1"
    if not (live_schema or replay_schema):
        return QuoteValidation(False, "unsupported_or_missing_quote_schema")

    source_mode = "provider"
    replay_source_ref = ""
    replay_epoch = ""
    replay_sequence = None
    if live_schema:
        required = (
            "event_time_utc",
            "recv_time_utc",
            "recv_monotonic_ns",
            "delta_volume",
            "volume",
            "open_interest",
            "volume_complete",
            "volume_quality",
            "trading_date",
            "event_session_date",
            "connection_generation",
            "ingest_seq",
            "quality_flags",
            "event_time_provenance",
            "continuity_status",
            "provider_source",
            "source_clock_quality",
            "receive_clock_quality",
            "freshness_status",
            "freshness_verified",
            "data_clock_qualified",
        )
        missing = [name for name in required if not _present(raw, name)]
        if missing:
            return QuoteValidation(False, "sdk_required_field_missing:" + ",".join(missing))
        if (
            _value(raw, "source_clock_quality") != "verified"
            or _value(raw, "receive_clock_quality") != "verified"
            or _value(raw, "freshness_status") != "fresh"
            or _value(raw, "freshness_verified") is not True
            or _value(raw, "data_clock_qualified") is not True
        ):
            return QuoteValidation(False, "provider_tick_clock_unqualified")
        if str(_value(raw, "volume_semantics", default="") or "").lower() != "delta":
            return QuoteValidation(False, "volume_semantics_not_delta")
    else:
        source_mode = str(_value(raw, "source_mode", default="") or "").lower()
        replay_source_ref = str(_value(raw, "replay_source_ref", default="") or "")
        replay_epoch = str(_value(raw, "replay_epoch", default="") or "")
        raw_replay_sequence = _value(raw, "replay_sequence", default=None)
        if source_mode not in {"replay", "synthetic"} or not replay_source_ref or not replay_epoch:
            return QuoteValidation(False, "replay_lineage_unavailable")
        if type(raw_replay_sequence) is not int or raw_replay_sequence <= 0:
            return QuoteValidation(False, "replay_sequence_invalid")
        replay_sequence = raw_replay_sequence
        if (
            _value(raw, "source_clock_quality") != "unknown"
            or _value(raw, "receive_clock_quality") != "unknown"
            or _value(raw, "freshness_status") != "unavailable"
            or _value(raw, "freshness_verified") is not False
            or _value(raw, "execution_eligible") is not False
            or _value(raw, "data_clock_qualified") is not False
        ):
            return QuoteValidation(False, "replay_live_eligibility_claim_invalid")
        live_identity_fields = (
            "received_at_utc",
            "recv_time_utc",
            "received_wall_time",
            "recv_monotonic_ns",
            "received_monotonic_ns",
            "connection_generation",
            "subscription_epoch",
            "ingest_seq",
            "provider_sequence",
            "clock_domain_id",
        )
        if any(_value(raw, name, default=None) is not None for name in live_identity_fields):
            return QuoteValidation(False, "replay_live_clock_field_present")
        if str(_value(raw, "volume_semantics", default="") or "").lower() != "delta":
            return QuoteValidation(False, "replay_volume_semantics_unavailable")

    raw_event_time = _value(raw, "event_time_utc", default=None)
    event_time = _epoch(raw_event_time)
    if event_time is None:
        return QuoteValidation(False, "invalid_event_time")
    recv_time_utc = None
    recv_monotonic = None
    ingest_seq = None
    generation = None
    if live_schema:
        recv_time_utc = _epoch(_value(raw, "recv_time_utc", default=None))
        if recv_time_utc is None:
            return QuoteValidation(False, "invalid_recv_time_utc")
        recv_ns = _value(raw, "recv_monotonic_ns", default=None)
        if type(recv_ns) is not int or recv_ns <= 0:
            return QuoteValidation(False, "invalid_recv_monotonic_ns")
        recv_monotonic = float(recv_ns) / 1_000_000_000.0
        try:
            ingest_seq = int(_value(raw, "ingest_seq"))
            generation = int(_value(raw, "connection_generation"))
        except (TypeError, ValueError, OverflowError):
            return QuoteValidation(False, "invalid_provider_causal_identity")
        if ingest_seq <= 0 or generation <= 0:
            return QuoteValidation(False, "invalid_provider_causal_identity")

    fields = {
        "bid": _value(raw, "bid_price", default=None),
        "ask": _value(raw, "ask_price", default=None),
        "bid_size": _value(raw, "bid_size", "bid_volume", default=None),
        "ask_size": _value(raw, "ask_size", "ask_volume", default=None),
        "last": _value(raw, "last_price", "price", default=None),
        "cum_volume": _value(raw, "cumulative_volume", "cum_volume", default=None),
        "delta_volume": _value(raw, "delta_volume", "volume", default=None),
        "open_interest": _value(raw, "open_interest", default=None),
        "lower_limit": _value(raw, "lower_limit", "lower_limit_price", default=None),
        "upper_limit": _value(raw, "upper_limit", "upper_limit_price", default=None),
    }
    for name, value in fields.items():
        if value is None and replay_schema and name == "cum_volume":
            continue
        if not _finite(value):
            return QuoteValidation(False, f"invalid_{name}")
    if live_schema and not math.isclose(
        float(_value(raw, "volume")), float(fields["delta_volume"]), rel_tol=0.0, abs_tol=1.0e-12
    ):
        return QuoteValidation(False, "delta_volume_alias_mismatch")
    bid = float(fields["bid"])
    ask = float(fields["ask"])
    bid_size = float(fields["bid_size"])
    ask_size = float(fields["ask_size"])
    last = float(fields["last"])
    if min(bid, ask, last) <= 0:
        return QuoteValidation(False, "nonpositive_price")
    if ask < bid:
        return QuoteValidation(False, "crossed_book")
    if bid_size < 0 or ask_size < 0 or bid_size + ask_size <= 0:
        return QuoteValidation(False, "invalid_depth")
    if not all(_on_tick_grid(price, float(tick_size)) for price in (bid, ask, last)):
        return QuoteValidation(False, "off_tick_grid")
    lower_limit = float(fields["lower_limit"])
    upper_limit = float(fields["upper_limit"])
    if not (0 < lower_limit < upper_limit):
        return QuoteValidation(False, "invalid_daily_price_limits")
    if not all(_on_tick_grid(price, float(tick_size)) for price in (lower_limit, upper_limit)):
        return QuoteValidation(False, "daily_price_limits_off_tick_grid")
    if bid < lower_limit or ask > upper_limit or not lower_limit <= last <= upper_limit:
        return QuoteValidation(False, "quote_outside_daily_price_limits")

    if live_schema and now_monotonic is not None:
        receive_age = float(now_monotonic) - float(recv_monotonic)
        if receive_age < -1.0e-9 or receive_age > max_receive_age:
            return QuoteValidation(False, "stale_receive_time")
    if live_schema and now_wall_utc is not None:
        event_age = float(now_wall_utc) - event_time
        if event_age < -1.0e-9 or event_age > max_event_age:
            return QuoteValidation(False, "stale_event_time")

    continuity = str(_value(raw, "continuity_status", default="") or "").lower()
    if continuity != "continuous":
        return QuoteValidation(False, "market_sequence_not_continuous")
    raw_quality_flags = _value(raw, "quality_flags", default=())
    if not isinstance(raw_quality_flags, (tuple, list, set, frozenset)):
        return QuoteValidation(False, "quality_flags_invalid")
    if raw_quality_flags:
        return QuoteValidation(False, "quality_flags_present")
    volume_complete = _value(raw, "volume_complete", default=False) is True
    if live_schema and not volume_complete:
        return QuoteValidation(False, "provider_volume_incomplete")
    if replay_schema and _value(raw, "volume_complete", default=False) is not True:
        return QuoteValidation(False, "replay_volume_incomplete")
    if float(fields["delta_volume"]) < 0:
        return QuoteValidation(False, "negative_delta_volume")
    cum_volume = fields["cum_volume"]
    if cum_volume is not None and float(cum_volume) < 0:
        return QuoteValidation(False, "negative_cumulative_volume")

    trading_day = _day_text(
        _value(raw, "trading_day" if replay_schema else "trading_date", default=None)
    )
    event_session_date = _day_text(_value(raw, "event_session_date", default=None))
    if not trading_day or not event_session_date:
        return QuoteValidation(False, "market_calendar_identity_missing")
    source = str(
        _value(raw, "provider_source", "source", default="") if live_schema
        else replay_source_ref
    )
    volume_quality = str(_value(raw, "volume_quality", default="") or "")
    event_time_source = str(
        _value(raw, "event_time_provenance", default="") if live_schema
        else "replay_event_time"
    )
    if live_schema and not source:
        return QuoteValidation(False, "provider_source_missing")
    if live_schema and not event_time_source:
        return QuoteValidation(False, "provider_event_time_provenance_missing")
    return QuoteValidation(
        True,
        "ok",
        QuoteSnapshot(
            event_time=event_time,
            recv_monotonic=recv_monotonic,
            ingest_seq=ingest_seq,
            bid=bid,
            ask=ask,
            bid_size=bid_size,
            ask_size=ask_size,
            last=last,
            cum_volume=float(cum_volume) if cum_volume is not None else None,
            delta_volume=float(fields["delta_volume"]),
            open_interest=float(fields["open_interest"]),
            lower_limit=lower_limit,
            upper_limit=upper_limit,
            trading_day=trading_day,
            event_session_date=event_session_date,
            generation=generation,
            source=source,
            schema_version=schema_version,
            recv_time_utc=recv_time_utc,
            volume_quality=volume_quality,
            event_time_source=event_time_source,
            continuity_status=continuity,
            volume_complete=volume_complete,
            source_mode=source_mode,
            replay_source_ref=replay_source_ref,
            replay_epoch=replay_epoch,
            replay_sequence=replay_sequence,
        ),
    )


@dataclass(frozen=True)
class FastFeatures:
    """Frozen quote-driven fast (H-side) feature bundle with readiness reasons."""

    ready: bool
    reasons: tuple[str, ...]
    event_time: float
    mid: Optional[float] = None
    spread_ticks: Optional[float] = None
    imbalance_5s: Optional[float] = None
    microprice: Optional[float] = None
    micro_dev: Optional[float] = None
    ofi_5s: Optional[float] = None
    momentum_15s: Optional[float] = None
    sigma_60s_price: Optional[float] = None
    mid_return_1s_ticks: Optional[float] = None
    valid_changes_60s: int = 0

    def as_dict(self) -> dict[str, Any]:
        """Return a plain dict copy for evidence serialization."""
        return asdict(self)


class QuoteFeatureWindow:
    """Bounded time-window calculator for the frozen v0 feature formulas."""

    def __init__(self, tick_size: float, retention_seconds: float = 62.5) -> None:
        """Validate the tick size and fix the quote retention horizon (minimum 62 s)."""
        if not _finite(tick_size) or float(tick_size) <= 0:
            raise ValueError("tick_size must be finite and positive")
        self.tick_size = float(tick_size)
        self.retention_seconds = max(float(retention_seconds), 62.0)
        self._quotes: Deque[QuoteSnapshot] = deque()
        self._last_ingest_seq = 0
        self._last_replay_sequence = 0
        self._sequence_scope = None
        self.invalid_count = 0
        self.last_invalid_reason = ""

    @property
    def quotes(self) -> tuple[QuoteSnapshot, ...]:
        """Return the retained quotes as an ordered tuple."""
        return tuple(self._quotes)

    def clear(self) -> None:
        """Drop retained quotes while preserving the active causal watermark."""
        self._quotes.clear()

    def add(self, quote: QuoteSnapshot) -> bool:
        """Append one ordered provider or replay quote without sharing cursors."""
        replay = quote.schema_version == "sdk.replay.market.tick.v1"
        scope = (
            ("replay", quote.source_mode, quote.replay_source_ref, quote.replay_epoch)
            if replay
            else ("provider",)
        )
        if self._sequence_scope is not None and scope != self._sequence_scope:
            self.invalid_count += 1
            self.last_invalid_reason = "quote_sequence_scope_changed"
            return False
        if replay:
            if quote.replay_sequence is None or quote.replay_sequence <= self._last_replay_sequence:
                self.invalid_count += 1
                self.last_invalid_reason = "nonincreasing_replay_sequence"
                return False
        elif quote.ingest_seq is None or quote.ingest_seq <= self._last_ingest_seq:
            self.invalid_count += 1
            self.last_invalid_reason = "nonincreasing_provider_ingest_seq"
            return False
        if self._quotes:
            previous = self._quotes[-1]
            if quote.event_time < previous.event_time:
                self.invalid_count += 1
                self.last_invalid_reason = "out_of_order_event_time"
                return False
        self._sequence_scope = scope
        self._quotes.append(quote)
        if replay:
            self._last_replay_sequence = int(quote.replay_sequence)
        else:
            self._last_ingest_seq = int(quote.ingest_seq)
        cutoff = quote.event_time - self.retention_seconds
        while len(self._quotes) > 1 and self._quotes[1].event_time < cutoff:
            self._quotes.popleft()
        return True

    @staticmethod
    def _clip(value: float) -> float:
        return max(-1.0, min(1.0, value))

    def _anchor(self, target: float, tolerance: float) -> Optional[QuoteSnapshot]:
        for quote in reversed(self._quotes):
            if quote.event_time <= target:
                if target - quote.event_time <= tolerance + 1.0e-9:
                    return quote
                return None
        return None

    def _time_weighted_imbalance(self, now: float) -> tuple[Optional[float], str]:
        cutoff = now - 5.0
        anchor = self._anchor(cutoff, 2.0)
        if anchor is None:
            return None, "imbalance_5s_anchor_missing"
        points = [anchor]
        points.extend(q for q in self._quotes if cutoff < q.event_time <= now)
        total = 0.0
        covered = 0.0
        for index, quote in enumerate(points):
            start = max(cutoff, quote.event_time)
            end = now if index + 1 == len(points) else min(now, points[index + 1].event_time)
            duration = end - start
            if duration < -1.0e-9:
                return None, "imbalance_5s_ordering"
            if duration > 2.0 + 1.0e-9:
                return None, "imbalance_5s_quote_gap"
            if duration > 0:
                total += quote.imbalance * duration
                covered += duration
        if covered < 5.0 - 1.0e-6:
            return None, "imbalance_5s_window_short"
        return self._clip(total / covered), ""

    def _ofi(self, now: float) -> tuple[Optional[float], str]:
        cutoff = now - 5.0
        anchor = self._anchor(cutoff, 2.0)
        if anchor is None:
            return None, "ofi_5s_anchor_missing"
        points = [anchor]
        points.extend(q for q in self._quotes if cutoff < q.event_time <= now)
        if len(points) < 2:
            return None, "ofi_5s_window_short"
        numerator = 0.0
        denominator = 0.0
        for previous, current in zip(points, points[1:]):
            if current.event_time - previous.event_time > 2.0 + 1.0e-9:
                return None, "ofi_5s_quote_gap"
            e_i = (
                (current.bid_size if current.bid >= previous.bid else 0.0)
                - (previous.bid_size if current.bid <= previous.bid else 0.0)
                - (current.ask_size if current.ask <= previous.ask else 0.0)
                + (previous.ask_size if current.ask >= previous.ask else 0.0)
            )
            numerator += e_i
            denominator += current.bid_size + current.ask_size
        if denominator <= 0:
            return None, "ofi_5s_zero_denominator"
        return self._clip(numerator / denominator), ""

    def _sigma(self, now: float) -> tuple[Optional[float], int, str]:
        cutoff = now - 60.0
        anchor = self._anchor(cutoff, 2.0)
        points: list[QuoteSnapshot] = []
        if anchor is not None:
            points.append(anchor)
        points.extend(q for q in self._quotes if cutoff < q.event_time <= now)
        changes = []
        for previous, current in zip(points, points[1:]):
            if current.event_time - previous.event_time > 2.0 + 1.0e-9:
                return None, len(changes), "sigma_60s_quote_gap"
            changes.append(current.mid - previous.mid)
        if len(changes) < 20:
            return None, len(changes), "sigma_60s_changes_lt_20"
        sigma = math.sqrt(sum(change * change for change in changes) / len(changes))
        if not math.isfinite(sigma):
            return None, len(changes), "sigma_60s_invalid"
        return sigma, len(changes), ""

    def calculate(self) -> FastFeatures:
        """Compute the frozen v0 fast features from the retained quote window."""
        if not self._quotes:
            return FastFeatures(False, ("no_quotes",), 0.0)
        current = self._quotes[-1]
        reasons: list[str] = []
        imbalance, reason = self._time_weighted_imbalance(current.event_time)
        if reason:
            reasons.append(reason)
        ofi, reason = self._ofi(current.event_time)
        if reason:
            reasons.append(reason)
        sigma, changes, reason = self._sigma(current.event_time)
        if reason:
            reasons.append(reason)
        anchor15 = self._anchor(current.event_time - 15.0, 2.0)
        if anchor15 is None:
            momentum = None
            reasons.append("momentum_15s_anchor_missing")
        elif sigma is None:
            momentum = None
        else:
            momentum = self._clip((current.mid - anchor15.mid) / max(self.tick_size, sigma))
        anchor1 = self._anchor(current.event_time - 1.0, 0.5)
        if anchor1 is None:
            mid_return_1s = None
            reasons.append("mid_return_1s_anchor_missing")
        else:
            mid_return_1s = (current.mid - anchor1.mid) / self.tick_size
        micro_dev = self._clip((current.microprice - current.mid) / self.tick_size)
        return FastFeatures(
            ready=not reasons,
            reasons=tuple(dict.fromkeys(reasons)),
            event_time=current.event_time,
            mid=current.mid,
            spread_ticks=(current.ask - current.bid) / self.tick_size,
            imbalance_5s=imbalance,
            microprice=current.microprice,
            micro_dev=micro_dev,
            ofi_5s=ofi,
            momentum_15s=momentum,
            sigma_60s_price=sigma,
            mid_return_1s_ticks=mid_return_1s,
            valid_changes_60s=changes,
        )


def quote_window_span(quotes: Iterable[QuoteSnapshot]) -> float:
    """Return the event-time span of ``quotes`` in seconds, or 0.0 when empty."""
    values = tuple(quotes)
    return max(values[-1].event_time - values[0].event_time, 0.0) if values else 0.0
