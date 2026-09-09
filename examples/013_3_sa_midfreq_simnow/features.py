"""Causal level-one quote features for the SA v0 candidate.

The CTP feed supplies snapshots rather than an order-by-order book.  OFI in
this module therefore measures quoted level-one changes only; it says nothing
about cancellations, aggressor side, queue position, or execution priority.
"""

from __future__ import annotations

import math
from datetime import datetime, timezone
from collections import deque
from dataclasses import asdict, dataclass
from typing import Any, Deque, Iterable, Optional

CTP_INVALID_ABS = 1.0e30


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

    ``_value`` is deliberately permissive for the legacy quote adapter.  The
    typed CTP v2 contract is different: required fields must be carried by the
    SDK event and may not be synthesized from a zero/default value here.
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
    return math.isfinite(number) and abs(number) < CTP_INVALID_ABS


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
    """Normalized, quality-checked best bid/ask snapshot."""

    event_time: float
    recv_monotonic: float
    ingest_seq: int
    bid: float
    ask: float
    bid_size: float
    ask_size: float
    last: float
    cum_volume: float
    delta_volume: float
    open_interest: float
    lower_limit: float
    upper_limit: float
    trading_day: str
    action_day: str
    connection_generation: int
    source: str
    schema_version: str = ""
    recv_time_utc: float = 0.0
    volume_quality: str = ""
    event_time_source: str = ""
    continuity_status: str = ""
    volume_complete: bool = False

    @property
    def mid(self) -> float:
        return (self.bid + self.ask) / 2.0

    @property
    def imbalance(self) -> float:
        return (self.bid_size - self.ask_size) / (self.bid_size + self.ask_size)

    @property
    def microprice(self) -> float:
        depth = self.bid_size + self.ask_size
        return (self.ask * self.bid_size + self.bid * self.ask_size) / depth


@dataclass(frozen=True)
class QuoteValidation:
    valid: bool
    reason: str
    quote: Optional[QuoteSnapshot] = None


def normalize_quote(
    raw: Any,
    *,
    tick_size: float,
    now_wall_utc: Optional[float] = None,
    now_monotonic: Optional[float] = None,
    max_receive_age: float = 2.0,
    max_event_age: float = 2.0,
) -> QuoteValidation:
    """Normalize one SDK/Store event without falling back to last or bar close."""

    if not _finite(tick_size) or float(tick_size) <= 0:
        return QuoteValidation(False, "invalid_tick_size")
    schema_version = str(_value(raw, "schema_version", default="") or "")
    if schema_version not in {"ctp.quote.v2", "backtrader.tick.v1"}:
        return QuoteValidation(False, "unsupported_or_missing_quote_schema")
    volume_semantics = str(_value(raw, "volume_semantics", default="") or "")
    if volume_semantics != "delta":
        return QuoteValidation(False, "volume_semantics_not_delta")
    strict_ctp_v2 = schema_version == "ctp.quote.v2"
    if strict_ctp_v2:
        required_groups = {
            "event_time_utc": ("event_time_utc",),
            "recv_time_utc": ("recv_time_utc",),
            "recv_monotonic_ns": ("recv_monotonic_ns",),
            "cum_volume": ("cum_volume", "cumulative_volume"),
            "delta_volume": ("delta_volume",),
            "volume": ("volume",),
            "open_interest": ("open_interest", "openinterest", "OpenInterest"),
            "volume_complete": ("volume_complete",),
            "volume_quality": ("volume_quality",),
            "trading_day": ("trading_day",),
            "action_day": ("action_day",),
            "connection_generation": ("connection_generation",),
            "ingest_seq": ("ingest_seq",),
            "quality_flags": ("quality_flags",),
            "event_time_source": ("event_time_source",),
            "continuity_status": ("continuity_status",),
            "source": ("source",),
        }
        missing = sorted(
            name for name, aliases in required_groups.items() if not _present(raw, *aliases)
        )
        if missing:
            return QuoteValidation(False, "ctp_required_field_missing:" + ",".join(missing))

    raw_event_time = (
        _value(raw, "event_time_utc")
        if strict_ctp_v2
        else _value(raw, "event_time_utc", "timestamp", "exchange_time")
    )
    event_time = _epoch(raw_event_time)
    if event_time is None:
        return QuoteValidation(False, "invalid_event_time")
    raw_recv_time = _value(raw, "recv_time_utc", default=None)
    recv_time_utc = _epoch(raw_recv_time) if raw_recv_time is not None else None
    if strict_ctp_v2 and recv_time_utc is None:
        return QuoteValidation(False, "invalid_recv_time_utc")
    recv_ns = (
        _value(raw, "recv_monotonic_ns", default=None)
        if strict_ctp_v2
        else _value(raw, "recv_monotonic_ns", "received_monotonic_ns", default=None)
    )
    recv_seconds = (
        None if strict_ctp_v2 else _value(raw, "recv_monotonic", "received_monotonic", default=None)
    )
    if recv_ns is not None:
        if (
            not _finite(recv_ns)
            or float(recv_ns) <= 0
            or (strict_ctp_v2 and not float(recv_ns).is_integer())
        ):
            return QuoteValidation(False, "invalid_recv_monotonic_ns")
        recv_monotonic = float(recv_ns) / 1_000_000_000.0
    elif recv_seconds is not None and _finite(recv_seconds):
        recv_monotonic = float(recv_seconds)
    else:
        return QuoteValidation(False, "missing_recv_monotonic")
    cum_volume = (
        _value(raw, "cum_volume", "cumulative_volume", default=None)
        if strict_ctp_v2
        else _value(raw, "cum_volume", "cumulative_volume", "Volume", default=0)
    )
    delta_volume = (
        _value(raw, "delta_volume", default=None)
        if strict_ctp_v2
        else _value(raw, "delta_volume", "volume", default=0)
    )
    fields = {
        "bid": _value(raw, "bid", "bid_price", "bid_price1", "BidPrice1"),
        "ask": _value(raw, "ask", "ask_price", "ask_price1", "AskPrice1"),
        "bid_size": _value(raw, "bid_size", "bid_volume", "bid_size1", "BidVolume1"),
        "ask_size": _value(raw, "ask_size", "ask_volume", "ask_size1", "AskVolume1"),
        "last": _value(raw, "last", "last_price", "price", "LastPrice"),
        "cum_volume": cum_volume,
        "delta_volume": delta_volume,
        "open_interest": _value(
            raw,
            "open_interest",
            "openinterest",
            "OpenInterest",
            default=None if strict_ctp_v2 else 0,
        ),
        "lower_limit": _value(raw, "lower_limit", "lower_limit_price", "LowerLimitPrice"),
        "upper_limit": _value(raw, "upper_limit", "upper_limit_price", "UpperLimitPrice"),
    }
    for name, value in fields.items():
        if not _finite(value):
            return QuoteValidation(False, f"invalid_{name}")
    if strict_ctp_v2:
        volume_alias = _value(raw, "volume", default=None)
        if not _finite(volume_alias):
            return QuoteValidation(False, "invalid_volume")
        if not math.isclose(
            float(volume_alias), float(fields["delta_volume"]), rel_tol=0.0, abs_tol=1.0e-12
        ):
            return QuoteValidation(False, "delta_volume_alias_mismatch")
        if _present(raw, "cum_volume") and _present(raw, "cumulative_volume"):
            first = _value(raw, "cum_volume", default=None)
            second = _value(raw, "cumulative_volume", default=None)
            if not (_finite(first) and _finite(second)) or not math.isclose(
                float(first), float(second), rel_tol=0.0, abs_tol=1.0e-12
            ):
                return QuoteValidation(False, "cumulative_volume_alias_mismatch")
    bid = float(fields["bid"])
    ask = float(fields["ask"])
    bid_size = float(fields["bid_size"])
    ask_size = float(fields["ask_size"])
    last = float(fields["last"])
    if min(bid, ask, last) <= 0:
        return QuoteValidation(False, "nonpositive_price")
    if ask < bid:
        return QuoteValidation(False, "crossed_book")
    if bid_size < 0 or ask_size < 0:
        return QuoteValidation(False, "negative_depth")
    if bid_size + ask_size <= 0:
        return QuoteValidation(False, "zero_depth")
    if not all(_on_tick_grid(price, float(tick_size)) for price in (bid, ask, last)):
        return QuoteValidation(False, "off_tick_grid")
    lower_limit = float(fields["lower_limit"])
    upper_limit = float(fields["upper_limit"])
    if not (0 < lower_limit < upper_limit):
        return QuoteValidation(False, "invalid_daily_price_limits")
    if not all(_on_tick_grid(price, float(tick_size)) for price in (lower_limit, upper_limit)):
        return QuoteValidation(False, "daily_price_limits_off_tick_grid")
    if bid < lower_limit or ask > upper_limit or last < lower_limit or last > upper_limit:
        return QuoteValidation(False, "quote_outside_daily_price_limits")
    if now_monotonic is not None:
        receive_age = float(now_monotonic) - recv_monotonic
        if receive_age < -1.0e-9 or receive_age > max_receive_age:
            return QuoteValidation(False, "stale_receive_time")
    if now_wall_utc is not None:
        event_age = float(now_wall_utc) - event_time
        if event_age < -1.0e-9 or event_age > max_event_age:
            return QuoteValidation(False, "stale_event_time")
    continuity = str(_value(raw, "continuity_status", "continuity", default="") or "").lower()
    raw_quality_flags = _value(raw, "quality_flags", default=None)
    if raw_quality_flags is None:
        if strict_ctp_v2:
            return QuoteValidation(False, "invalid_quality_flags")
        quality_flags = ()
    elif isinstance(raw_quality_flags, (tuple, list, set, frozenset)):
        quality_flags = tuple(raw_quality_flags)
    else:
        return QuoteValidation(False, "invalid_quality_flags")
    if strict_ctp_v2 and continuity != "continuous":
        return QuoteValidation(False, f"ctp_continuity_not_continuous:{continuity or 'missing'}")
    if bool(_value(raw, "stale", default=False)) or continuity in {
        "gap",
        "stale",
        "disconnected",
        "out_of_order",
        "checksum_failed",
    }:
        return QuoteValidation(False, f"unhealthy_continuity:{continuity or 'unknown'}")
    if quality_flags:
        return QuoteValidation(False, "quality_flags:" + ",".join(map(str, quality_flags)))
    if float(fields["delta_volume"]) < 0 or float(fields["cum_volume"]) < 0:
        return QuoteValidation(False, "negative_volume")

    if strict_ctp_v2:
        trading_day = str(_value(raw, "trading_day", default="") or "")
        action_day = str(_value(raw, "action_day", default="") or "")
        raw_ingest_seq = _value(raw, "ingest_seq", default=0)
    else:
        trading_day = str(_value(raw, "trading_day", "TradingDay", default="") or "")
        action_day = str(_value(raw, "action_day", "ActionDay", default="") or "")
        raw_ingest_seq = _value(raw, "ingest_seq", "sequence", default=0)
    try:
        ingest_seq = int(raw_ingest_seq or 0)
        connection_generation = int(_value(raw, "connection_generation", default=0) or 0)
    except (TypeError, ValueError, OverflowError):
        return QuoteValidation(False, "invalid_causal_identity")
    source = str(_value(raw, "source", default="") or "")
    volume_quality = str(_value(raw, "volume_quality", default="") or "")
    event_time_source = str(_value(raw, "event_time_source", default="") or "")
    if strict_ctp_v2:
        if not trading_day or not action_day:
            return QuoteValidation(False, "ctp_calendar_identity_missing")
        if ingest_seq <= 0 or connection_generation <= 0 or not source:
            return QuoteValidation(False, "ctp_causal_identity_missing")
        if _value(raw, "volume_complete", default=None) is not True:
            return QuoteValidation(False, "ctp_volume_incomplete")
        if volume_quality.lower() != "continuous":
            return QuoteValidation(
                False, f"ctp_volume_quality_not_continuous:{volume_quality or 'missing'}"
            )
        if not event_time_source:
            return QuoteValidation(False, "ctp_event_time_source_missing")

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
            cum_volume=float(fields["cum_volume"]),
            delta_volume=float(fields["delta_volume"]),
            open_interest=float(fields["open_interest"]),
            lower_limit=lower_limit,
            upper_limit=upper_limit,
            trading_day=trading_day,
            action_day=action_day,
            connection_generation=connection_generation,
            source=source or "backtrader",
            schema_version=schema_version,
            recv_time_utc=float(recv_time_utc or 0.0),
            volume_quality=volume_quality,
            event_time_source=event_time_source,
            continuity_status=continuity,
            volume_complete=True,
        ),
    )


@dataclass(frozen=True)
class FastFeatures:
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
        return asdict(self)


class QuoteFeatureWindow:
    """Bounded time-window calculator for the frozen v0 feature formulas."""

    def __init__(self, tick_size: float, retention_seconds: float = 62.5) -> None:
        if not _finite(tick_size) or float(tick_size) <= 0:
            raise ValueError("tick_size must be finite and positive")
        self.tick_size = float(tick_size)
        self.retention_seconds = max(float(retention_seconds), 62.0)
        self._quotes: Deque[QuoteSnapshot] = deque()
        self._last_ingest_seq = 0
        self.invalid_count = 0
        self.last_invalid_reason = ""

    @property
    def quotes(self) -> tuple[QuoteSnapshot, ...]:
        return tuple(self._quotes)

    def clear(self) -> None:
        self._quotes.clear()

    def add(self, quote: QuoteSnapshot) -> bool:
        if quote.ingest_seq <= self._last_ingest_seq:
            self.invalid_count += 1
            self.last_invalid_reason = "nonincreasing_global_ingest_seq"
            return False
        if self._quotes:
            previous = self._quotes[-1]
            if quote.event_time < previous.event_time:
                self.invalid_count += 1
                self.last_invalid_reason = "out_of_order_event_time"
                return False
        self._quotes.append(quote)
        self._last_ingest_seq = quote.ingest_seq
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
    values = tuple(quotes)
    return max(values[-1].event_time - values[0].event_time, 0.0) if values else 0.0
