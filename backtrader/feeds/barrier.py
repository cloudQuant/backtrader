"""Immutable closed-bar evidence and a small multi-leg causal barrier.

The feed owns construction of a bar.  This module owns the point at which a
consumer may use several already-closed bars together.  It intentionally does
not aggregate ticks, query a store, create orders, or consult a process clock.
Callers provide the recorded receive/seal times, including for replay.  That
keeps a fast replay from accidentally becoming evidence that a live barrier
was met.

``BarEvidence`` is the public hand-off from a feed to a strategy.  A
``MultiLegBarBarrier`` accepts exactly two or three such objects and emits one
immutable ``MinuteDecisionInput`` per complete, same-scope bucket.  Once a
bucket is emitted or skipped, a later bar cannot revise or back-fill it.
"""

from __future__ import annotations

import math
from collections import OrderedDict, deque
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from types import MappingProxyType
from typing import Any, Dict, Iterable, List, Optional, Tuple

from .ctpcohort import CtpQuoteEvidence

UTC = timezone.utc
_GOOD_QUALITY = frozenset({"GOOD", "OK", "COMPLETE", "VALID"})
_MAX_ABS_NUMBER = 1.0e30
_MISSING = object()
_PROVENANCE_PLACEHOLDERS = frozenset(
    {"unknown", "unverified", "n/a", "na", "none", "null", "unset", "placeholder"}
)


def _value(item: Any, *names: str, default: Any = None) -> Any:
    if isinstance(item, Mapping):
        for name in names:
            if name in item:
                return item[name]
        return default
    for name in names:
        if hasattr(item, name):
            result = getattr(item, name)
            if result is not None:
                return result
    return default


def _alias(item: Any, *names: str, default: Any = _MISSING) -> Any:
    """Read aliases only when every supplied spelling carries the same value."""

    values = []
    if isinstance(item, Mapping):
        values = [(name, item[name]) for name in names if name in item]
    else:
        values = [(name, getattr(item, name)) for name in names if hasattr(item, name)]
    if not values:
        return default
    first = values[0][1]
    if any(value != first for _, value in values[1:]):
        fields = ", ".join(name for name, _ in values)
        raise ValueError(f"conflicting aliases: {fields}")
    return first


def _text(value: Any, field: str, *, allow_empty: bool = False) -> str:
    if not isinstance(value, str) or (not allow_empty and not value) or value.strip() != value:
        raise ValueError(f"{field} must be an exact non-empty string")
    return value


def _provenance_text(value: Any, field: str) -> str:
    value = _text(value, field)
    if value.casefold() in _PROVENANCE_PLACEHOLDERS:
        raise ValueError(f"{field} must identify a verified provenance scope")
    return value


def _number(value: Any, field: str, *, nonnegative: bool = False) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{field} must be a finite number")
    result = float(value)
    if not math.isfinite(result) or abs(result) >= _MAX_ABS_NUMBER:
        raise ValueError(f"{field} must be a finite number")
    if not nonnegative and result <= 0:
        raise ValueError(f"{field} must be positive")
    if nonnegative and result < 0:
        raise ValueError(f"{field} must be non-negative")
    return result


def _datetime(value: Any, field: str) -> datetime:
    """Return an aware UTC time.

    Naive datetimes are interpreted as UTC only for deterministic local
    replay fixtures.  Live producers should provide an aware UTC value.
    """

    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, (int, float)) and not isinstance(value, bool):
        try:
            parsed = datetime.fromtimestamp(float(value), UTC)
        except (OverflowError, OSError, ValueError) as error:
            raise ValueError(f"{field} must be a valid UTC time") from error
    elif isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError as error:
            raise ValueError(f"{field} must be a valid UTC time") from error
    else:
        raise ValueError(f"{field} must be a valid UTC time")
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        parsed = parsed.replace(tzinfo=UTC)
    else:
        parsed = parsed.astimezone(UTC)
    return parsed


def _optional_datetime(value: Any, field: str) -> Optional[datetime]:
    return None if value is None else _datetime(value, field)


def _valid_trading_day(value: str) -> bool:
    if len(value) != 8 or not value.isascii() or not value.isdecimal():
        return False
    try:
        datetime.strptime(value, "%Y%m%d")
    except ValueError:
        return False
    return True


def _mono(value: Any, field: str) -> float:
    """Normalize a caller-supplied monotonic reading to seconds.

    ``seal_received_mono`` is intentionally in seconds because the public
    barrier deadlines are seconds.  A nanosecond alias is accepted and
    converted exactly once for integration with CTP event metadata.
    """

    return _number(value, field, nonnegative=True)


def _bar_seal_monotonic(item: Any) -> Any:
    """Adapt explicit seconds/ns feed aliases without inferring units."""

    seconds = _alias(item, "seal_received_mono", "received_monotonic", default=_MISSING)
    nanoseconds = _alias(
        item,
        "seal_received_monotonic_ns",
        "received_monotonic_ns",
        "recv_monotonic_ns",
        default=_MISSING,
    )
    if seconds is _MISSING and nanoseconds is _MISSING:
        return _MISSING
    converted = None
    if nanoseconds is not _MISSING:
        if type(nanoseconds) is not int or nanoseconds <= 0:
            raise ValueError("seal monotonic nanosecond fields must be positive integers")
        converted = nanoseconds / 1_000_000_000.0
    if seconds is not _MISSING:
        parsed = _mono(seconds, "seal_received_mono")
        if converted is not None and not math.isclose(
            parsed, converted, rel_tol=0.0, abs_tol=1.0e-12
        ):
            raise ValueError("conflicting aliases: seal monotonic units")
        return parsed
    return converted


def _json_safe(value: Any) -> Any:
    if isinstance(value, ClockMapping):
        return value.to_dict()
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, Mapping):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (tuple, list, set, frozenset)):
        return [_json_safe(item) for item in value]
    return value


def _freeze(value: Any) -> Any:
    """Recursively detach mutable mappings and sequences in evidence."""

    if isinstance(value, Mapping):
        return MappingProxyType({_freeze(key): _freeze(item) for key, item in value.items()})
    if isinstance(value, list):
        return tuple(_freeze(item) for item in value)
    if isinstance(value, tuple):
        return tuple(_freeze(item) for item in value)
    if isinstance(value, set):
        return frozenset(_freeze(item) for item in value)
    if isinstance(value, frozenset):
        return frozenset(_freeze(item) for item in value)
    if hasattr(value, "__dict__"):
        return MappingProxyType({_freeze(key): _freeze(item) for key, item in vars(value).items()})
    return value


def _time_is_explicitly_aware(value: Any) -> bool:
    if isinstance(value, datetime):
        return value.tzinfo is not None and value.utcoffset() is not None
    if isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return False
        return parsed.tzinfo is not None and parsed.utcoffset() is not None
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _delta_nanoseconds(later: datetime, earlier: datetime) -> int:
    """Return an exact integral nanosecond delta for two UTC datetimes."""

    delta = later - earlier
    return (
        (delta.days * 24 * 60 * 60) + delta.seconds
    ) * 1_000_000_000 + delta.microseconds * 1_000


@dataclass(frozen=True)
class ClockMapping:
    """A caller-provided wall/monotonic mapping used for barrier deadlines.

    The mapping is evidence, rather than a convenience conversion.  It must
    carry the sampled anchor, its clock domain and generation, a named source,
    a finite error bound, an expiry, and the rules identity.  Replay fixtures
    set ``synthetic=True`` explicitly; live evidence cannot use a synthetic
    mapping.  No process clock is read here.
    """

    mapping_id: str
    wall_utc_at_anchor: Any
    mono_ns_at_anchor: int
    clock_domain_id: str
    connection_generation: int
    source: str
    error_bound_ns: int
    valid_until_mono_ns: int
    rules_hash: str
    synthetic: bool = False

    def __post_init__(self) -> None:
        _provenance_text(self.mapping_id, "mapping_id")
        anchor = self.wall_utc_at_anchor
        if not _time_is_explicitly_aware(anchor):
            raise ValueError("wall_utc_at_anchor must carry an explicit timezone")
        anchor = _datetime(anchor, "wall_utc_at_anchor")
        if type(self.mono_ns_at_anchor) is not int or self.mono_ns_at_anchor < 0:
            raise ValueError("mono_ns_at_anchor must be a non-negative integer")
        _provenance_text(self.clock_domain_id, "clock_domain_id")
        if type(self.connection_generation) is not int or self.connection_generation <= 0:
            raise ValueError("connection_generation must be a positive integer")
        _provenance_text(self.source, "source")
        if type(self.error_bound_ns) is not int or self.error_bound_ns < 0:
            raise ValueError("error_bound_ns must be a non-negative integer")
        if type(self.valid_until_mono_ns) is not int:
            raise ValueError("valid_until_mono_ns must be an integer")
        if self.valid_until_mono_ns <= self.mono_ns_at_anchor:
            raise ValueError("valid_until_mono_ns must be after the anchor")
        _provenance_text(self.rules_hash, "rules_hash")
        if not isinstance(self.synthetic, bool):
            raise ValueError("synthetic must be a bool")
        object.__setattr__(self, "wall_utc_at_anchor", anchor)

    def map_wall_to_mono_ns(self, wall_time: Any) -> int:
        """Map a wall time while refusing values outside this mapping's scope."""

        wall = _datetime(wall_time, "mapped_wall_time")
        mapped = self.mono_ns_at_anchor + _delta_nanoseconds(wall, self.wall_utc_at_anchor)
        if mapped < 0:
            raise ValueError("mapped monotonic time must be non-negative")
        return mapped

    def validate_pair(self, wall_time: Any, mono_seconds: Any) -> None:
        """Check one observed wall/monotonic pair against the error interval."""

        mono = _number(mono_seconds, "mapped_monotonic", nonnegative=True)
        actual_ns = int(round(mono * 1_000_000_000.0))
        mapped_ns = self.map_wall_to_mono_ns(wall_time)
        if abs(actual_ns - mapped_ns) > self.error_bound_ns:
            raise ValueError("wall/monotonic pair exceeds mapping error bound")
        if mapped_ns + self.error_bound_ns > self.valid_until_mono_ns:
            raise ValueError("clock mapping is expired")
        if actual_ns > self.valid_until_mono_ns:
            raise ValueError("clock mapping is expired")

    def conservative_deadline_seconds(self, wall_deadline: Any) -> float:
        """Return the earliest monotonic deadline allowed by the error bound."""

        mapped_ns = self.map_wall_to_mono_ns(wall_deadline)
        if mapped_ns + self.error_bound_ns > self.valid_until_mono_ns:
            raise ValueError("clock mapping expires before the deadline")
        conservative_ns = max(0, mapped_ns - self.error_bound_ns)
        return conservative_ns / 1_000_000_000.0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "mapping_id": self.mapping_id,
            "wall_utc_at_anchor": self.wall_utc_at_anchor.isoformat(),
            "mono_ns_at_anchor": self.mono_ns_at_anchor,
            "clock_domain_id": self.clock_domain_id,
            "connection_generation": self.connection_generation,
            "source": self.source,
            "error_bound_ns": self.error_bound_ns,
            "valid_until_mono_ns": self.valid_until_mono_ns,
            "rules_hash": self.rules_hash,
            "synthetic": self.synthetic,
        }


@dataclass(frozen=True)
class BarLeg:
    """One exact expected instrument identity for a barrier."""

    symbol: str
    exchange: str

    def __post_init__(self) -> None:
        _text(self.symbol, "symbol")
        _text(self.exchange, "exchange")


@dataclass(frozen=True)
class BarBarrierPolicy:
    """Time and quality policy shared by 23 and 24 consumers."""

    timeframe_seconds: float = 60.0
    timeout_seconds: float = 2.0
    max_quote_skew_ms: float = 500.0

    def __post_init__(self) -> None:
        timeframe = _number(self.timeframe_seconds, "timeframe_seconds")
        timeout = _number(self.timeout_seconds, "timeout_seconds")
        skew = _number(self.max_quote_skew_ms, "max_quote_skew_ms", nonnegative=True)
        object.__setattr__(self, "timeframe_seconds", timeframe)
        object.__setattr__(self, "timeout_seconds", timeout)
        object.__setattr__(self, "max_quote_skew_ms", skew)


class BarBarrierReason:
    """Stable result codes for evidence and barrier decisions."""

    READY = "READY"
    WAITING_FOR_LEGS = "WAITING_FOR_LEGS"
    WAITING_FOR_WATERMARK = "WAITING_FOR_WATERMARK"
    UNKNOWN_SYMBOL = "UNKNOWN_SYMBOL"
    SYMBOL_MISMATCH = "SYMBOL_MISMATCH"
    EXCHANGE_MISMATCH = "EXCHANGE_MISMATCH"
    CANDIDATE_MISMATCH = "CANDIDATE_MISMATCH"
    BUCKET_MISMATCH = "BUCKET_MISMATCH"
    SESSION_MISMATCH = "SESSION_MISMATCH"
    TRADING_DAY_MISMATCH = "TRADING_DAY_MISMATCH"
    GENERATION_MISMATCH = "GENERATION_MISMATCH"
    RULES_HASH_MISMATCH = "RULES_HASH_MISMATCH"
    CLOCK_DOMAIN_MISMATCH = "CLOCK_DOMAIN_MISMATCH"
    CLOCK_MODE_MISMATCH = "CLOCK_MODE_MISMATCH"
    CLOCK_MAPPING_MISSING = "CLOCK_MAPPING_MISSING"
    CLOCK_MAPPING_MISMATCH = "CLOCK_MAPPING_MISMATCH"
    CLOCK_INVALID = "CLOCK_INVALID"
    CLOCK_REGRESSION = "CLOCK_REGRESSION"
    SCOPE_RESET_REQUIRED = "SCOPE_RESET_REQUIRED"
    INVALID_BAR = "INVALID_BAR"
    SKIP_INCOMPLETE_MINUTE = "SKIP_INCOMPLETE_MINUTE"
    SKIP_BARRIER_TIMEOUT = "SKIP_BARRIER_TIMEOUT"
    FUTURE_DATA_REJECTED = "FUTURE_DATA_REJECTED"
    DUPLICATE_BAR = "DUPLICATE_BAR"
    REVISION_REJECTED = "REVISION_REJECTED"
    LATE_BAR_REJECTED = "LATE_BAR_REJECTED"
    FUTURE_SEAL_REJECTED = "FUTURE_SEAL_REJECTED"
    BLOCKED_QUOTE_CUTOFF = "BLOCKED_QUOTE_CUTOFF"
    BLOCKED_CROSS_LEG_SKEW = "BLOCKED_CROSS_LEG_SKEW"
    QUOTE_AFTER_CUTOFF = "QUOTE_AFTER_CUTOFF"
    QUOTE_AFTER_SEAL = "QUOTE_AFTER_SEAL"
    QUOTE_FUTURE_DATA = "QUOTE_FUTURE_DATA"
    QUOTE_SCOPE_MISMATCH = "QUOTE_SCOPE_MISMATCH"
    QUOTE_EXCHANGE_MISMATCH = "QUOTE_EXCHANGE_MISMATCH"
    QUOTE_IDENTITY_CONFLICT = "QUOTE_IDENTITY_CONFLICT"
    QUOTE_IDENTITY_MISSING = "QUOTE_IDENTITY_MISSING"
    QUOTE_TRADING_DAY_MISMATCH = "QUOTE_TRADING_DAY_MISMATCH"
    QUOTE_RULES_HASH_MISMATCH = "QUOTE_RULES_HASH_MISMATCH"
    QUOTE_QUALITY_INVALID = "QUOTE_QUALITY_INVALID"
    QUOTE_DUPLICATE = "QUOTE_DUPLICATE"
    QUOTE_NOT_IN_FROZEN_INPUT = "QUOTE_NOT_IN_FROZEN_INPUT"
    NO_FROZEN_INPUT = "NO_FROZEN_INPUT"


def _bar_quality_is_good(bar: "BarEvidence") -> bool:
    quality = bar.quality
    if isinstance(quality, str):
        return quality.upper() in _GOOD_QUALITY
    return False


@dataclass(frozen=True)
class BarEvidence:
    """An immutable feed-produced closed OHLCV bar.

    The object carries both trade-bar provenance and the independently frozen
    quote cutoff used by the 24 minute consumer.  ``quote_events`` are
    optional because the 23 consumer is deliberately bar-only.
    """

    symbol: str
    exchange: str
    bucket_start: Any
    bucket_end: Any
    available_at: Any
    seal_received_mono: Any
    trading_day: str
    generation: int
    session_segment: str
    rules_hash: str
    quality: Any = _MISSING
    volume_complete: Any = _MISSING
    first_ingest_seq: int = 0
    last_ingest_seq: int = 0
    quote_cutoff_seq: Any = _MISSING
    bar_id: str = ""
    bar_sequence: int = 0
    closure_reason: str = "watermark"
    watermark: Any = None
    max_event_time: Any = None
    open: float = 0.0
    high: float = 0.0
    low: float = 0.0
    close: float = 0.0
    volume: float = 0.0
    openinterest: float = 0.0
    quote_events: Tuple[Any, ...] = ()
    clock_domain: Any = _MISSING
    clock_mode: Any = _MISSING
    seal_received_at: Any = _MISSING
    candidate_id: str = ""
    timeframe_seconds: Optional[float] = None
    trade_count: Optional[int] = None
    complete: Any = _MISSING
    clock_mapping: Any = _MISSING

    def __post_init__(self) -> None:
        _text(self.symbol, "symbol")
        _text(self.exchange, "exchange")
        raw_mode = self.clock_mode
        if raw_mode == "live":
            for field_name, raw in (
                ("bucket_start", self.bucket_start),
                ("bucket_end", self.bucket_end),
                ("available_at", self.available_at),
                ("seal_received_at", self.seal_received_at),
                ("watermark", self.watermark),
                ("max_event_time", self.max_event_time),
            ):
                if raw is not None and not _time_is_explicitly_aware(raw):
                    raise ValueError(f"{field_name} must carry an explicit timezone in live mode")
        start = _datetime(self.bucket_start, "bucket_start")
        end = _datetime(self.bucket_end, "bucket_end")
        available = _datetime(self.available_at, "available_at")
        if end <= start:
            raise ValueError("bucket_end must be after bucket_start")
        if available < end:
            raise ValueError("available_at must be at or after bucket_end")
        object.__setattr__(self, "bucket_start", start)
        object.__setattr__(self, "bucket_end", end)
        object.__setattr__(self, "available_at", available)

        _text(self.session_segment, "session_segment")
        if type(self.generation) is not int or self.generation <= 0:
            raise ValueError("generation must be a positive integer")
        _text(self.trading_day, "trading_day")
        if not _valid_trading_day(self.trading_day):
            raise ValueError("trading_day must be a valid YYYYMMDD date")
        _provenance_text(self.rules_hash, "rules_hash")

        if self.clock_domain is _MISSING:
            raise ValueError("clock_domain is required")
        _provenance_text(self.clock_domain, "clock_domain")
        mode = self.clock_mode
        if mode is _MISSING:
            raise ValueError("clock_mode is required")
        if mode not in {"replay", "live"}:
            raise ValueError("clock_mode must be replay or live")
        if mode == "live":
            if self.seal_received_at is None:
                raise ValueError("seal_received_at is required in live mode")
            if self.quote_cutoff_seq is _MISSING:
                raise ValueError("quote_cutoff_seq is required in live mode")
        object.__setattr__(self, "clock_domain", self.clock_domain)

        seal_mono = self.seal_received_mono
        if seal_mono is _MISSING:
            raise ValueError("seal_received_mono is required")
        seal_mono = _mono(seal_mono, "seal_received_mono")
        if seal_mono <= 0:
            raise ValueError("seal_received_mono must be positive")
        object.__setattr__(self, "seal_received_mono", seal_mono)

        seal_at = self.seal_received_at
        if seal_at is _MISSING or seal_at is None:
            raise ValueError("seal_received_at is required")
        if not _time_is_explicitly_aware(seal_at) and mode == "live":
            raise ValueError("seal_received_at must carry an explicit timezone in live mode")
        seal_at = _datetime(seal_at, "seal_received_at")
        mapping = self.clock_mapping
        if mapping is _MISSING or not isinstance(mapping, ClockMapping):
            raise ValueError("clock_mapping is required")
        if mapping.clock_domain_id != self.clock_domain:
            raise ValueError("clock_mapping clock domain does not match bar")
        if mapping.connection_generation != self.generation:
            raise ValueError("clock_mapping generation does not match bar")
        if mapping.rules_hash != self.rules_hash:
            raise ValueError("clock_mapping rules hash does not match bar")
        if mode == "replay" and not mapping.synthetic:
            raise ValueError("replay bars require an explicitly synthetic clock mapping")
        if mode == "live" and mapping.synthetic:
            raise ValueError("live bars cannot use a synthetic clock mapping")
        object.__setattr__(self, "seal_received_at", _datetime(seal_at, "seal_received_at"))
        mapping.validate_pair(seal_at, seal_mono)
        object.__setattr__(self, "clock_mapping", mapping)
        object.__setattr__(self, "watermark", _optional_datetime(self.watermark, "watermark"))
        object.__setattr__(
            self, "max_event_time", _optional_datetime(self.max_event_time, "max_event_time")
        )

        for field_name in ("open", "high", "low", "close", "volume", "openinterest"):
            raw = getattr(self, field_name)
            if isinstance(raw, bool) or not isinstance(raw, (int, float)):
                raise ValueError(f"{field_name} must be numeric")
            parsed = float(raw)
            if not math.isfinite(parsed) or abs(parsed) >= _MAX_ABS_NUMBER:
                raise ValueError(f"{field_name} must be finite")
            object.__setattr__(self, field_name, parsed)

        for field_name in ("first_ingest_seq", "last_ingest_seq", "bar_sequence"):
            raw = getattr(self, field_name)
            if type(raw) is not int or raw <= 0:
                raise ValueError(f"{field_name} must be a positive integer")
        if self.last_ingest_seq < self.first_ingest_seq:
            raise ValueError("last_ingest_seq must not precede first_ingest_seq")
        if self.quote_cutoff_seq is _MISSING:
            raise ValueError("quote_cutoff_seq is required")
        cutoff = self.quote_cutoff_seq
        if type(cutoff) is not int or cutoff < 0 or cutoff < self.last_ingest_seq:
            raise ValueError("quote_cutoff_seq must be an integer at or after last_ingest_seq")
        object.__setattr__(self, "quote_cutoff_seq", cutoff)
        if self.trade_count is not None and (
            type(self.trade_count) is not int or self.trade_count < 0
        ):
            raise ValueError("trade_count must be a non-negative integer or None")
        if self.quality is _MISSING or not isinstance(self.quality, str) or not self.quality:
            raise ValueError("quality is required")
        if not isinstance(self.volume_complete, bool) or not isinstance(self.complete, bool):
            raise ValueError("volume_complete and complete must be explicit bool values")
        _text(self.closure_reason, "closure_reason")
        if self.candidate_id:
            _text(self.candidate_id, "candidate_id")
        timeframe = self.timeframe_seconds
        if timeframe is not None:
            object.__setattr__(self, "timeframe_seconds", _number(timeframe, "timeframe_seconds"))

        raw_quotes = self.quote_events
        if not isinstance(raw_quotes, (tuple, list)):
            raise ValueError("quote_events must be a tuple or list")
        frozen_quotes = []
        for event in raw_quotes:
            if isinstance(event, CtpQuoteEvidence):
                frozen_quotes.append(event)
            elif isinstance(event, Mapping):
                frozen_quotes.append(_freeze(dict(event)))
            elif hasattr(event, "__dict__"):
                frozen_quotes.append(_freeze(vars(event)))
            else:
                raise ValueError("quote_events must contain mappings or event objects")
        frozen_quotes = tuple(frozen_quotes)
        object.__setattr__(self, "quote_events", frozen_quotes)

        bar_id = self.bar_id
        if not bar_id:
            bar_id = (
                f"{self.symbol}:{start.isoformat()}:{end.isoformat()}:"
                f"{self.generation}:{self.first_ingest_seq}-{self.last_ingest_seq}"
            )
        _text(bar_id, "bar_id")
        object.__setattr__(self, "bar_id", bar_id)

    def to_dict(self) -> Dict[str, Any]:
        return {
            name: _json_safe(getattr(self, name))
            for name in (
                "symbol",
                "exchange",
                "bucket_start",
                "bucket_end",
                "available_at",
                "seal_received_mono",
                "seal_received_at",
                "trading_day",
                "generation",
                "session_segment",
                "rules_hash",
                "quality",
                "volume_complete",
                "first_ingest_seq",
                "last_ingest_seq",
                "quote_cutoff_seq",
                "bar_id",
                "bar_sequence",
                "closure_reason",
                "watermark",
                "max_event_time",
                "open",
                "high",
                "low",
                "close",
                "volume",
                "openinterest",
                "quote_events",
                "clock_domain",
                "clock_mode",
                "clock_mapping",
                "candidate_id",
                "timeframe_seconds",
                "trade_count",
                "complete",
            )
        }


@dataclass(frozen=True)
class MinuteDecisionInput:
    """One frozen, same-scope multi-leg decision input."""

    key: Tuple[Any, ...]
    bars: Mapping[str, BarEvidence]
    bucket_start: datetime
    bucket_end: datetime
    common_available_at: datetime
    bar_ids: Tuple[str, ...]
    quote_cutoffs: Mapping[str, int]
    accepted_quotes: Mapping[str, Tuple[Mapping[str, Any], ...]]
    quote_rejections: Mapping[str, Tuple[str, ...]]
    source_sequences: Mapping[str, Tuple[int, int]]
    quality_report: Mapping[str, Any]
    trading_day: str
    generation: int
    session_segment: str
    rules_hash: str
    candidate_id: str
    clock_domain: str
    clock_mode: str
    barrier_ready_mono: float
    deadline_mono: float
    clock_mapping: ClockMapping

    def __post_init__(self) -> None:
        bars = dict(self.bars)
        if not bars or any(not isinstance(bar, BarEvidence) for bar in bars.values()):
            raise ValueError("bars must contain BarEvidence values")
        if not isinstance(self.clock_mapping, ClockMapping):
            raise ValueError("clock_mapping is required")
        object.__setattr__(self, "key", tuple(self.key))
        object.__setattr__(self, "bar_ids", tuple(self.bar_ids))
        object.__setattr__(self, "bars", MappingProxyType(bars))
        object.__setattr__(self, "quote_cutoffs", _freeze(dict(self.quote_cutoffs)))
        object.__setattr__(self, "accepted_quotes", _freeze(dict(self.accepted_quotes)))
        object.__setattr__(self, "quote_rejections", _freeze(dict(self.quote_rejections)))
        object.__setattr__(self, "source_sequences", _freeze(dict(self.source_sequences)))
        object.__setattr__(self, "quality_report", _freeze(dict(self.quality_report)))

    def to_dict(self) -> Dict[str, Any]:
        return {
            "key": _json_safe(self.key),
            "bars": {symbol: bar.to_dict() for symbol, bar in self.bars.items()},
            "bucket_start": self.bucket_start.isoformat(),
            "bucket_end": self.bucket_end.isoformat(),
            "common_available_at": self.common_available_at.isoformat(),
            "bar_ids": list(self.bar_ids),
            "quote_cutoffs": dict(self.quote_cutoffs),
            "accepted_quotes": _json_safe(self.accepted_quotes),
            "quote_rejections": _json_safe(self.quote_rejections),
            "source_sequences": _json_safe(self.source_sequences),
            "quality_report": _json_safe(self.quality_report),
            "trading_day": self.trading_day,
            "generation": self.generation,
            "session_segment": self.session_segment,
            "rules_hash": self.rules_hash,
            "candidate_id": self.candidate_id,
            "clock_domain": self.clock_domain,
            "clock_mode": self.clock_mode,
            "barrier_ready_mono": self.barrier_ready_mono,
            "deadline_mono": self.deadline_mono,
            "clock_mapping": self.clock_mapping.to_dict(),
        }


@dataclass(frozen=True)
class BarBarrierResult:
    """Result of one bar ingestion or clock advance."""

    reason: str
    decision_input: Optional[MinuteDecisionInput] = None
    key: Optional[Tuple[Any, ...]] = None
    reset_warmup: bool = False

    @property
    def ready(self) -> bool:
        return self.decision_input is not None


@dataclass(frozen=True)
class QuoteCutoffResult:
    """Side-effect-free validation result for a quote against a frozen bar."""

    accepted: bool
    reason: str
    symbol: Optional[str] = None
    event: Optional[Mapping[str, Any]] = None


def _quote_mapping(event: Any, *, bar: BarEvidence) -> Optional[Dict[str, Any]]:
    """Detach a raw quote or adapt an already validated CTP quote evidence."""

    if isinstance(event, CtpQuoteEvidence):
        return {
            "symbol": event.symbol,
            "exchange": event.exchange,
            "event_time": event.source_epoch,
            "received_at": event.receive_epoch,
            "received_monotonic_ns": event.receive_monotonic_ns,
            "ingest_seq": event.ingest_seq,
            "generation": event.connection_generation,
            "asset_type": event.asset_type,
            "bid": event.bid,
            "ask": event.ask,
            "bid_size": event.bid_size,
            "ask_size": event.ask_size,
            "last": event.last,
            "lower_limit": event.lower_limit,
            "upper_limit": event.upper_limit,
            "subscription_epoch": event.subscription_epoch,
            "trading_day": event.trading_day,
            "action_day": event.action_day,
            "rules_hash": event.rules_hash,
            "clock_domain": event.clock_domain_id,
            "clock_mode": bar.clock_mode,
            "session_segment": bar.session_segment,
            "candidate_id": bar.candidate_id,
            "quality": "GOOD",
            "volume_complete": True,
            "source": event.source,
            "event_time_source": event.event_time_source,
            "source_clock_error_ms": event.source_clock_error_ms,
            "receive_clock_error_ms": event.receive_clock_error_ms,
            "validated_quote_type": "CtpQuoteEvidence",
        }
    if isinstance(event, Mapping):
        return dict(event)
    if hasattr(event, "__dict__"):
        return dict(vars(event))
    return None


def _quote_monotonic_seconds(event: Mapping[str, Any]) -> float:
    """Normalize seconds and nanosecond aliases without guessing units."""

    seconds = _alias(
        event,
        "received_monotonic",
        "recv_monotonic",
        "receive_monotonic",
        default=_MISSING,
    )
    nanoseconds = _alias(
        event,
        "received_monotonic_ns",
        "recv_monotonic_ns",
        "receive_monotonic_ns",
        default=_MISSING,
    )
    parsed_seconds = None
    parsed_nanoseconds = None
    if seconds is not _MISSING:
        parsed_seconds = _number(seconds, "quote.received_monotonic", nonnegative=True)
    if nanoseconds is not _MISSING:
        if type(nanoseconds) is not int or nanoseconds < 0:
            raise ValueError("quote monotonic nanosecond fields must be integers")
        parsed_nanoseconds = nanoseconds / 1_000_000_000.0
    if parsed_seconds is None and parsed_nanoseconds is None:
        raise ValueError("quote receive monotonic evidence is required")
    if (
        parsed_seconds is not None
        and parsed_nanoseconds is not None
        and not math.isclose(parsed_seconds, parsed_nanoseconds, rel_tol=0.0, abs_tol=1.0e-12)
    ):
        raise ValueError("conflicting aliases: quote receive monotonic units")
    return parsed_seconds if parsed_seconds is not None else parsed_nanoseconds


def _quote_filter(
    event: Any,
    *,
    bar: BarEvidence,
    max_skew_ms: float,
) -> QuoteCutoffResult:
    data = _quote_mapping(event, bar=bar)
    if data is None:
        return QuoteCutoffResult(False, BarBarrierReason.BLOCKED_QUOTE_CUTOFF)
    try:
        symbol = _alias(data, "symbol", "instrument_id", "InstrumentID", default=_MISSING)
        exchange = _alias(data, "exchange", "exchange_id", "ExchangeID", default=_MISSING)
        sequence = _alias(data, "ingest_seq", "sequence", default=_MISSING)
        generation = _alias(data, "generation", "connection_generation", default=_MISSING)
        trading_day = _alias(data, "trading_day", "TradingDay", default=_MISSING)
        rules_hash = _alias(data, "rules_hash", default=_MISSING)
        domain = _alias(data, "clock_domain", "clock_domain_id", default=_MISSING)
        mode = _alias(data, "clock_mode", default=_MISSING)
        quality = _alias(data, "quality", "quote_quality", "quality_status", default=_MISSING)
        volume_complete = _alias(data, "volume_complete", default=_MISSING)
        session = _alias(data, "session_segment", "session", default=_MISSING)
        candidate = _alias(data, "candidate_id", default=_MISSING)
        event_time_raw = _alias(
            data,
            "event_time",
            "event_time_utc",
            "exchange_time",
            default=_MISSING,
        )
        receive_time_raw = _alias(
            data,
            "received_at",
            "recv_time_utc",
            "received_wall_time",
            "receive_time",
            default=_MISSING,
        )
        if symbol != bar.symbol:
            return QuoteCutoffResult(False, BarBarrierReason.QUOTE_SCOPE_MISMATCH, symbol=symbol)
        if exchange != bar.exchange:
            return QuoteCutoffResult(False, BarBarrierReason.QUOTE_EXCHANGE_MISMATCH, symbol=symbol)
        if type(sequence) is not int or sequence <= 0:
            return QuoteCutoffResult(False, BarBarrierReason.BLOCKED_QUOTE_CUTOFF, symbol=symbol)
        if sequence > bar.quote_cutoff_seq:
            return QuoteCutoffResult(False, BarBarrierReason.QUOTE_AFTER_CUTOFF, symbol=symbol)
        if type(generation) is not int or generation <= 0:
            return QuoteCutoffResult(False, BarBarrierReason.QUOTE_IDENTITY_MISSING, symbol=symbol)
        if generation != bar.generation:
            return QuoteCutoffResult(False, BarBarrierReason.GENERATION_MISMATCH, symbol=symbol)
        if not isinstance(trading_day, str):
            return QuoteCutoffResult(False, BarBarrierReason.QUOTE_IDENTITY_MISSING, symbol=symbol)
        if trading_day != bar.trading_day:
            return QuoteCutoffResult(
                False, BarBarrierReason.QUOTE_TRADING_DAY_MISMATCH, symbol=symbol
            )
        if not isinstance(rules_hash, str):
            return QuoteCutoffResult(False, BarBarrierReason.QUOTE_IDENTITY_MISSING, symbol=symbol)
        if rules_hash != bar.rules_hash:
            return QuoteCutoffResult(
                False, BarBarrierReason.QUOTE_RULES_HASH_MISMATCH, symbol=symbol
            )
        if not isinstance(domain, str):
            return QuoteCutoffResult(False, BarBarrierReason.QUOTE_IDENTITY_MISSING, symbol=symbol)
        if domain != bar.clock_domain:
            return QuoteCutoffResult(False, BarBarrierReason.CLOCK_DOMAIN_MISMATCH, symbol=symbol)
        if mode is _MISSING or mode != bar.clock_mode:
            return QuoteCutoffResult(False, BarBarrierReason.CLOCK_MODE_MISMATCH, symbol=symbol)
        if not isinstance(session, str) or session != bar.session_segment:
            return QuoteCutoffResult(False, BarBarrierReason.QUOTE_SCOPE_MISMATCH, symbol=symbol)
        if bar.candidate_id and (candidate is _MISSING or candidate != bar.candidate_id):
            return QuoteCutoffResult(False, BarBarrierReason.QUOTE_SCOPE_MISMATCH, symbol=symbol)
        if (
            quality is _MISSING
            or not isinstance(quality, str)
            or quality.upper() not in _GOOD_QUALITY
        ):
            return QuoteCutoffResult(False, BarBarrierReason.QUOTE_QUALITY_INVALID, symbol=symbol)
        if volume_complete is not True:
            return QuoteCutoffResult(False, BarBarrierReason.BLOCKED_QUOTE_CUTOFF, symbol=symbol)
        if event_time_raw is _MISSING or receive_time_raw is _MISSING:
            return QuoteCutoffResult(False, BarBarrierReason.BLOCKED_QUOTE_CUTOFF, symbol=symbol)
        if bar.clock_mode == "live" and (
            not _time_is_explicitly_aware(event_time_raw)
            or not _time_is_explicitly_aware(receive_time_raw)
        ):
            return QuoteCutoffResult(False, BarBarrierReason.BLOCKED_QUOTE_CUTOFF, symbol=symbol)
        received_mono = _quote_monotonic_seconds(data)
    except (TypeError, ValueError) as error:
        symbol = _value(data, "symbol", "instrument_id", "InstrumentID")
        reason = (
            BarBarrierReason.QUOTE_IDENTITY_CONFLICT
            if str(error).startswith("conflicting aliases")
            else BarBarrierReason.BLOCKED_QUOTE_CUTOFF
        )
        return QuoteCutoffResult(False, reason, symbol=symbol)
    try:
        event_time = _datetime(event_time_raw, "quote.event_time")
        receive_time = _datetime(receive_time_raw, "quote.received_at")
    except ValueError:
        return QuoteCutoffResult(False, BarBarrierReason.BLOCKED_QUOTE_CUTOFF, symbol=symbol)
    if event_time >= bar.bucket_end:
        return QuoteCutoffResult(False, BarBarrierReason.QUOTE_FUTURE_DATA, symbol=symbol)
    if receive_time > bar.seal_received_at:
        return QuoteCutoffResult(False, BarBarrierReason.QUOTE_AFTER_SEAL, symbol=symbol)
    if received_mono > bar.seal_received_mono:
        return QuoteCutoffResult(False, BarBarrierReason.QUOTE_AFTER_SEAL, symbol=symbol)
    if event_time > receive_time:
        return QuoteCutoffResult(False, BarBarrierReason.QUOTE_FUTURE_DATA, symbol=symbol)
    try:
        # Receive wall time and monotonic time are one observation.  Validate
        # them against the bar's frozen mapping before admitting the event;
        # comparing each field only with its own cutoff would permit a stale
        # monotonic value to masquerade as a historical quote.
        bar.clock_mapping.validate_pair(receive_time, received_mono)
    except ValueError:
        return QuoteCutoffResult(False, BarBarrierReason.CLOCK_MAPPING_MISMATCH, symbol=symbol)
    # This function is a frozen-bar cutoff check.  Full native CTP quote-v2
    # quality/schema validation remains the public CtpQuoteCohortValidator;
    # this boundary still requires enough explicit scope to prevent a raw,
    # under-specified quote from entering a minute decision.
    del max_skew_ms
    data.update(
        {
            "symbol": symbol,
            "exchange": exchange,
            "event_time": event_time,
            "received_at": receive_time,
            "received_monotonic": received_mono,
            "ingest_seq": sequence,
            "generation": generation,
            "trading_day": trading_day,
            "rules_hash": rules_hash,
            "session_segment": session,
            "clock_domain": domain,
            "clock_mode": mode,
            "quality": quality,
            "volume_complete": volume_complete,
        }
    )
    return QuoteCutoffResult(True, BarBarrierReason.READY, symbol=symbol, event=_freeze(data))


def validate_quote_against_bar(
    event: Any, *, bar: BarEvidence, max_skew_ms: float = 500.0
) -> QuoteCutoffResult:
    """Validate one quote without mutating a barrier or its decision input."""

    return _quote_filter(event, bar=bar, max_skew_ms=max_skew_ms)


class MultiLegBarBarrier:
    """Causal two- or three-leg barrier for already-closed bars."""

    _MAX_PENDING_BUCKETS = 128
    _MAX_RETAINED_INPUTS = 64
    _MAX_RESULT_HISTORY = 128

    def __init__(
        self,
        expected_legs: Optional[Iterable[Any]] = None,
        *,
        legs: Optional[Iterable[Any]] = None,
        candidate_id: str = "",
        expected_rules_hash: Optional[str] = None,
        clock_mapping: Optional[ClockMapping] = None,
        policy: Optional[BarBarrierPolicy] = None,
        timeframe_seconds: Optional[float] = None,
        timeout_seconds: Optional[float] = None,
        expected_clock_domain: Optional[str] = None,
        clock_domain: Optional[str] = None,
        clock_mode: Optional[str] = None,
        expected_exchange: str = "",
    ) -> None:
        source = expected_legs if expected_legs is not None else legs
        if source is None:
            raise ValueError("expected_legs is required")
        self.expected_legs = self._normalize_legs(source, expected_exchange)
        if len(self.expected_legs) not in (2, 3):
            raise ValueError("a barrier requires exactly two or three legs")
        self._leg_by_symbol = {leg.symbol: leg for leg in self.expected_legs}
        if len(self._leg_by_symbol) != len(self.expected_legs):
            raise ValueError("expected leg symbols must be unique")
        self.candidate_id = _text(candidate_id, "candidate_id", allow_empty=True)
        self.expected_rules_hash = (
            None
            if expected_rules_hash is None
            else _text(expected_rules_hash, "expected_rules_hash")
        )
        if clock_mapping is not None and not isinstance(clock_mapping, ClockMapping):
            raise TypeError("clock_mapping must be ClockMapping")
        self.clock_mapping = clock_mapping
        if policy is None:
            policy = BarBarrierPolicy(
                timeframe_seconds=60.0 if timeframe_seconds is None else timeframe_seconds,
                timeout_seconds=2.0 if timeout_seconds is None else timeout_seconds,
            )
        if not isinstance(policy, BarBarrierPolicy):
            raise TypeError("policy must be BarBarrierPolicy")
        self.policy = policy
        if (
            expected_clock_domain is not None
            and clock_domain is not None
            and expected_clock_domain != clock_domain
        ):
            raise ValueError("expected_clock_domain and clock_domain aliases must agree")
        self.expected_clock_domain = (
            expected_clock_domain if expected_clock_domain is not None else clock_domain
        )
        if self.expected_clock_domain is not None:
            _text(self.expected_clock_domain, "expected_clock_domain")
        self.clock_mode = clock_mode
        if self.clock_mode is not None and self.clock_mode not in {"replay", "live"}:
            raise ValueError("clock_mode must be replay or live")
        self._pending: Dict[Tuple[Any, ...], Dict[str, Any]] = {}
        self._pending_core: Dict[Tuple[Any, ...], Tuple[Any, ...]] = {}
        self._skipped: "OrderedDict[Tuple[Any, ...], str]" = OrderedDict()
        self._finalized: "OrderedDict[Tuple[Any, ...], MinuteDecisionInput]" = OrderedDict()
        # A bucket watermark belongs to the active physical connection and
        # clock domain.  A new connection may reuse a wall-time bucket in an
        # independent replay; the same connection, including recalibration,
        # must move beyond the old bucket.
        self._retired_bucket_end: Optional[datetime] = None
        self._last_input: Optional[MinuteDecisionInput] = None
        self._last_results = deque(maxlen=self._MAX_RESULT_HISTORY)
        self._last_now_mono: Optional[float] = None
        self._clock_fault: Optional[str] = None
        # Bind the first valid input to one immutable identity scope.  A
        # cross-scope or clock fault retires that scope until reset_scope is
        # given a complete replacement declaration.
        self._scope: Optional[Tuple[Any, ...]] = None
        self._retired_scopes: "OrderedDict[Tuple[Any, ...], None]" = OrderedDict()
        # Connection generation, clock calibration, and business session are
        # independent dimensions.  Keep only the greatest generation and its
        # greatest calibration anchor for each clock identity.  These scalar
        # fences survive the bounded retired-scope cache and never compare
        # monotonic values belonging to different clock domains.
        self._generation_fence_by_clock: Dict[Tuple[Any, ...], int] = {}
        self._mapping_fence_by_clock: Dict[Tuple[Any, ...], Tuple[datetime, int]] = {}
        self._mapping_by_clock: Dict[Tuple[Any, ...], ClockMapping] = {}
        self._bucket_context_by_clock: Dict[Tuple[Any, ...], Tuple[int, datetime, int]] = {}
        self._bucket_watermark_by_clock: Dict[Tuple[Any, ...], datetime] = {}
        self._active_clock_key: Optional[Tuple[Any, ...]] = None
        self._active_connection_marker: Optional[Tuple[int, datetime, int]] = None

    @staticmethod
    def _normalize_legs(source: Iterable[Any], default_exchange: str) -> Tuple[BarLeg, ...]:
        if isinstance(source, Mapping):
            items = list(source.items())
            result: List[BarLeg] = []
            for key, raw in items:
                if isinstance(raw, BarLeg):
                    result.append(raw)
                elif isinstance(raw, Mapping):
                    result.append(
                        BarLeg(
                            symbol=raw.get("symbol", key),
                            exchange=raw.get("exchange", default_exchange),
                        )
                    )
                else:
                    result.append(BarLeg(symbol=str(raw), exchange=default_exchange))
            return tuple(result)
        result = []
        for raw in source:
            if isinstance(raw, BarLeg):
                result.append(raw)
            elif isinstance(raw, Mapping):
                result.append(
                    BarLeg(symbol=raw["symbol"], exchange=raw.get("exchange", default_exchange))
                )
            else:
                result.append(BarLeg(symbol=str(raw), exchange=default_exchange))
        return tuple(result)

    @property
    def pending_keys(self) -> Tuple[Tuple[Any, ...], ...]:
        return tuple(self._pending)

    @property
    def finalized_inputs(self) -> Mapping[Tuple[Any, ...], MinuteDecisionInput]:
        return MappingProxyType(dict(self._finalized))

    @property
    def last_input(self) -> Optional[MinuteDecisionInput]:
        return self._last_input

    def reset_scope(
        self,
        *,
        trading_day: Optional[str] = None,
        generation: Optional[int] = None,
        session_segment: Optional[str] = None,
        rules_hash: Optional[str] = None,
        clock_domain: Optional[str] = None,
        clock_mode: Optional[str] = None,
        clock_mapping: Optional[ClockMapping] = None,
        candidate_id: Optional[str] = None,
    ) -> None:
        """Bind a newly authorized scope and recorded wall/mono mapping.

        An empty call deliberately does *not* reopen the barrier.  It retires
        any pending scope and leaves the barrier requiring a complete
        declaration, which prevents ``reset_scope()`` from being used as a
        cache-clearing back-fill operation.  A real reset must state every
        time/identity dimension and provide the new mapping.
        """

        supplied = (
            trading_day,
            generation,
            session_segment,
            rules_hash,
            clock_domain,
            clock_mode,
            clock_mapping,
            candidate_id,
        )
        if all(value is None for value in supplied):
            self._retire_bound_scope()
            for key in list(self._pending):
                self._mark_skipped(key, BarBarrierReason.SCOPE_RESET_REQUIRED)
            self._pending.clear()
            self._pending_core.clear()
            self._finalized.clear()
            self._last_input = None
            self._clock_fault = BarBarrierReason.SCOPE_RESET_REQUIRED
            self._scope = None
            return
        if any(value is None for value in supplied[:7]):
            raise ValueError(
                "reset_scope requires trading_day, generation, session_segment, rules_hash, "
                "clock_domain, clock_mode and clock_mapping"
            )
        if candidate_id is None:
            candidate_id = self.candidate_id
        _text(candidate_id, "candidate_id", allow_empty=True)
        _text(trading_day, "trading_day")
        if not _valid_trading_day(trading_day):
            raise ValueError("trading_day must be a valid YYYYMMDD date")
        if type(generation) is not int or generation <= 0:
            raise ValueError("generation must be a positive integer")
        _text(session_segment, "session_segment")
        _provenance_text(rules_hash, "rules_hash")
        _provenance_text(clock_domain, "clock_domain")
        if clock_mode not in {"replay", "live"}:
            raise ValueError("clock_mode must be replay or live")
        if not isinstance(clock_mapping, ClockMapping):
            raise ValueError("clock_mapping must be a ClockMapping")
        if clock_mapping.clock_domain_id != clock_domain:
            raise ValueError("clock_mapping clock domain does not match scope")
        if clock_mapping.connection_generation != generation:
            raise ValueError("clock_mapping generation does not match scope")
        if clock_mapping.rules_hash != rules_hash:
            raise ValueError("clock_mapping rules hash does not match scope")
        if clock_mode == "replay" and not clock_mapping.synthetic:
            raise ValueError("replay scope requires an explicitly synthetic clock mapping")
        if clock_mode == "live" and clock_mapping.synthetic:
            raise ValueError("live scope cannot use a synthetic clock mapping")
        if self.candidate_id and candidate_id != self.candidate_id:
            raise ValueError("scope candidate_id does not match barrier")
        if self.expected_rules_hash is not None and rules_hash != self.expected_rules_hash:
            raise ValueError("scope rules_hash does not match barrier")
        if self.expected_clock_domain is not None and clock_domain != self.expected_clock_domain:
            raise ValueError("scope clock_domain does not match barrier")
        if self.clock_mode is not None and clock_mode != self.clock_mode:
            raise ValueError("scope clock_mode does not match barrier")
        if self.clock_mapping is not None and clock_mapping != self.clock_mapping:
            self._invalidate_scope(BarBarrierReason.CLOCK_MAPPING_MISMATCH)
            raise ValueError("scope clock_mapping does not match barrier")

        requested_scope = self._scope_from_values(
            candidate_id,
            trading_day,
            generation,
            session_segment,
            rules_hash,
            clock_domain,
            clock_mode,
            clock_mapping,
        )
        if requested_scope == self._scope or requested_scope in self._retired_scopes:
            raise ValueError("reset_scope cannot reopen an active or retired scope")
        lifecycle_reason = self._scope_lifecycle_reason(requested_scope)
        if lifecycle_reason is not None:
            if lifecycle_reason == BarBarrierReason.CLOCK_MAPPING_MISMATCH:
                self._invalidate_scope(lifecycle_reason)
                raise ValueError("reset_scope received an incompatible clock mapping")
            raise ValueError("reset_scope cannot move the lifecycle fence backwards")

        requested_clock_key = self._scope_clock_key(requested_scope)
        requested_marker = self._scope_connection_marker(requested_scope)
        # The anchor is calibration metadata, not physical connection
        # identity.  Once lifecycle validation accepts an equivalent
        # recalibration, retain observations from the same generation/domain.
        preserve_clock_observation = (
            self._active_clock_key == requested_clock_key
            and self._active_connection_marker is not None
            and self._active_connection_marker[0] == requested_marker[0]
        )

        self._retire_bound_scope()
        for key in list(self._pending):
            self._mark_skipped(key, BarBarrierReason.SCOPE_RESET_REQUIRED)
        self._pending.clear()
        self._pending_core.clear()
        self._finalized.clear()
        self._last_input = None
        self._last_results.clear()
        if not preserve_clock_observation:
            self._last_now_mono = None
        self._clock_fault = None
        self._scope = requested_scope
        self._record_scope_lifecycle(requested_scope)

    @staticmethod
    def _scope_from_values(*values: Any) -> Tuple[Any, ...]:
        return tuple(values)

    def _scope_for(self, bar: BarEvidence) -> Tuple[Any, ...]:
        return self._scope_from_values(
            self._candidate_for(bar),
            bar.trading_day,
            bar.generation,
            bar.session_segment,
            bar.rules_hash,
            bar.clock_domain,
            bar.clock_mode,
            bar.clock_mapping,
        )

    def _retire_bound_scope(self) -> None:
        if self._scope is None:
            return
        self._retired_scopes[self._scope] = None
        self._retired_scopes.move_to_end(self._scope)
        while len(self._retired_scopes) > self._MAX_RETAINED_INPUTS:
            self._retired_scopes.popitem(last=False)

    @staticmethod
    def _scope_clock_key(scope: Tuple[Any, ...]) -> Tuple[Any, ...]:
        """Return the identity whose monotonic observations are comparable."""

        # Candidate/rules/mode are part of the evidence contract.  The clock
        # domain keeps unrelated monotonic counters from being compared.
        return (scope[0], scope[4], scope[5], scope[6])

    @staticmethod
    def _scope_connection_marker(scope: Tuple[Any, ...]) -> Tuple[int, datetime, int]:
        """Return generation plus the recorded wall/mono calibration anchor."""

        mapping = scope[7]
        return (
            scope[2],
            mapping.wall_utc_at_anchor,
            mapping.mono_ns_at_anchor,
        )

    def _scope_lifecycle_reason(self, scope: Tuple[Any, ...]) -> Optional[str]:
        """Reject connection/calibration rollback without ordering sessions."""

        clock_key = self._scope_clock_key(scope)
        generation = scope[2]
        anchor = (scope[7].wall_utc_at_anchor, scope[7].mono_ns_at_anchor)
        seen_generation = self._generation_fence_by_clock.get(clock_key)
        if seen_generation is not None and generation < seen_generation:
            return BarBarrierReason.SCOPE_RESET_REQUIRED
        if seen_generation is None or generation > seen_generation:
            return None
        prior_mapping = self._mapping_by_clock.get(clock_key)
        if (
            prior_mapping is not None
            and scope[7] != prior_mapping
            and not self._mappings_are_continuous(prior_mapping, scope[7])
        ):
            return BarBarrierReason.CLOCK_MAPPING_MISMATCH
        # An incompatible calibration must take the existing fault-latching
        # path even when its anchor also moves backwards.  Checking the
        # lifecycle anchor first would return SCOPE_RESET_REQUIRED and leave
        # the clock usable after the caller supplied contradictory evidence.
        # Equivalent recalibrations still use the anchor fence below.
        seen_anchor = self._mapping_fence_by_clock.get(clock_key)
        if seen_anchor is not None and anchor < seen_anchor:
            return BarBarrierReason.SCOPE_RESET_REQUIRED
        return None

    @staticmethod
    def _mappings_are_continuous(previous: ClockMapping, current: ClockMapping) -> bool:
        """Check that two calibrations describe one uninterrupted clock."""

        if (
            previous.clock_domain_id != current.clock_domain_id
            or previous.connection_generation != current.connection_generation
            or previous.rules_hash != current.rules_hash
        ):
            return False
        try:
            expected_current_anchor = previous.map_wall_to_mono_ns(current.wall_utc_at_anchor)
        except ValueError:
            return False
        tolerance = previous.error_bound_ns + current.error_bound_ns
        return abs(current.mono_ns_at_anchor - expected_current_anchor) <= tolerance

    def _record_scope_lifecycle(self, scope: Tuple[Any, ...]) -> None:
        """Record connection/mapping fences and activate the bucket watermark."""

        clock_key = self._scope_clock_key(scope)
        marker = self._scope_connection_marker(scope)
        generation = marker[0]
        anchor = marker[1:]
        seen_generation = self._generation_fence_by_clock.get(clock_key)
        is_new_connection = seen_generation is None or generation > seen_generation
        prior_mapping = self._mapping_by_clock.get(clock_key)
        is_new_mapping = not is_new_connection and prior_mapping != scope[7]
        if is_new_connection or is_new_mapping:
            self._generation_fence_by_clock[clock_key] = generation
            self._mapping_fence_by_clock[clock_key] = anchor
            self._mapping_by_clock[clock_key] = scope[7]
            self._bucket_context_by_clock[clock_key] = marker
            if is_new_connection:
                self._bucket_watermark_by_clock.pop(clock_key, None)
        self._active_clock_key = clock_key
        self._active_connection_marker = marker
        if self._bucket_context_by_clock.get(clock_key) == marker:
            self._retired_bucket_end = self._bucket_watermark_by_clock.get(clock_key)
        else:
            self._retired_bucket_end = None

    def _record_bucket_watermark(self, bucket_end: datetime) -> None:
        """Advance the bounded active-connection bucket high-water mark."""

        if self._active_clock_key is None or self._active_connection_marker is None:
            if self._retired_bucket_end is None or bucket_end > self._retired_bucket_end:
                self._retired_bucket_end = bucket_end
            return
        if (
            self._bucket_context_by_clock.get(self._active_clock_key)
            != self._active_connection_marker
        ):
            return
        prior = self._bucket_watermark_by_clock.get(self._active_clock_key)
        if prior is None or bucket_end > prior:
            self._bucket_watermark_by_clock[self._active_clock_key] = bucket_end
            self._retired_bucket_end = bucket_end

    def _latch_scope_fault(self, reason: str) -> None:
        self._retire_bound_scope()
        self._scope = None
        self._clock_fault = reason
        # A fault invalidates the active consumer pointer, while finalized
        # inputs remain available through ``finalized_inputs`` for audit.
        # Keeping the pointer would let an old READY input authorize a quote
        # after the clock or scope has become unsafe.
        self._last_input = None

    def _observe_seal(self, seal_received_mono: float) -> None:
        """Advance the same-domain observation fence on an accepted seal."""

        if self._last_now_mono is None or seal_received_mono > self._last_now_mono:
            self._last_now_mono = seal_received_mono

    def _candidate_for(self, bar: BarEvidence) -> str:
        return bar.candidate_id or self.candidate_id

    def _key(self, bar: BarEvidence) -> Tuple[Any, ...]:
        return (
            self._candidate_for(bar),
            bar.trading_day,
            bar.generation,
            bar.session_segment,
            bar.bucket_start,
            bar.bucket_end,
            bar.rules_hash,
        )

    def _core(self, bar: BarEvidence) -> Tuple[Any, ...]:
        return (self._candidate_for(bar), bar.bucket_start, bar.bucket_end)

    def _identity_reason(self, bar: BarEvidence, key: Tuple[Any, ...]) -> Optional[str]:
        leg = self._leg_by_symbol.get(bar.symbol)
        if leg is None:
            return BarBarrierReason.UNKNOWN_SYMBOL
        if bar.exchange != leg.exchange:
            return BarBarrierReason.EXCHANGE_MISMATCH
        if self.candidate_id and bar.candidate_id != self.candidate_id:
            return BarBarrierReason.CANDIDATE_MISMATCH
        if self.expected_rules_hash is not None and bar.rules_hash != self.expected_rules_hash:
            return BarBarrierReason.RULES_HASH_MISMATCH
        if (
            self.expected_clock_domain is not None
            and bar.clock_domain != self.expected_clock_domain
        ):
            return BarBarrierReason.CLOCK_DOMAIN_MISMATCH
        if self.clock_mode is not None and bar.clock_mode != self.clock_mode:
            return BarBarrierReason.CLOCK_MODE_MISMATCH
        if self.clock_mapping is not None and bar.clock_mapping != self.clock_mapping:
            return BarBarrierReason.CLOCK_MAPPING_MISMATCH
        if bar.timeframe_seconds is not None and not math.isclose(
            bar.timeframe_seconds,
            self.policy.timeframe_seconds,
            rel_tol=0.0,
            abs_tol=1.0e-9,
        ):
            return BarBarrierReason.BUCKET_MISMATCH
        if self._scope is not None:
            current = self._scope
            incoming = self._scope_for(bar)
            for index, reason in (
                (0, BarBarrierReason.CANDIDATE_MISMATCH),
                (1, BarBarrierReason.TRADING_DAY_MISMATCH),
                (2, BarBarrierReason.GENERATION_MISMATCH),
                (3, BarBarrierReason.SESSION_MISMATCH),
                (4, BarBarrierReason.RULES_HASH_MISMATCH),
                (5, BarBarrierReason.CLOCK_DOMAIN_MISMATCH),
                (6, BarBarrierReason.CLOCK_MODE_MISMATCH),
                (7, BarBarrierReason.CLOCK_MAPPING_MISMATCH),
            ):
                if incoming[index] != current[index]:
                    return reason
        del key
        return None

    def _bar_reason(self, bar: BarEvidence) -> Optional[str]:
        if not _bar_quality_is_good(bar) or not bar.complete:
            return BarBarrierReason.SKIP_INCOMPLETE_MINUTE
        if bar.volume_complete is not True:
            return BarBarrierReason.SKIP_INCOMPLETE_MINUTE
        if not math.isclose(
            (bar.bucket_end - bar.bucket_start).total_seconds(),
            self.policy.timeframe_seconds,
            rel_tol=0.0,
            abs_tol=1.0e-9,
        ):
            return BarBarrierReason.BUCKET_MISMATCH
        if bar.available_at > bar.bucket_end + timedelta(seconds=self.policy.timeout_seconds):
            return BarBarrierReason.SKIP_BARRIER_TIMEOUT
        if bar.seal_received_at < bar.bucket_end:
            return BarBarrierReason.SKIP_INCOMPLETE_MINUTE
        if bar.seal_received_at > bar.bucket_end + timedelta(seconds=self.policy.timeout_seconds):
            return BarBarrierReason.SKIP_BARRIER_TIMEOUT
        if bar.watermark is None or bar.watermark < bar.bucket_end:
            return BarBarrierReason.SKIP_INCOMPLETE_MINUTE
        if bar.trade_count is None or bar.trade_count <= 0 or bar.volume <= 0:
            return BarBarrierReason.SKIP_INCOMPLETE_MINUTE
        if bar.high < bar.low or min(bar.open, bar.high, bar.low, bar.close) <= 0:
            return BarBarrierReason.INVALID_BAR
        if bar.first_ingest_seq <= 0 or bar.last_ingest_seq <= 0:
            return BarBarrierReason.INVALID_BAR
        if bar.max_event_time is not None and bar.max_event_time >= bar.bucket_end:
            return BarBarrierReason.FUTURE_DATA_REJECTED
        if bar.first_ingest_seq > bar.last_ingest_seq:
            return BarBarrierReason.INVALID_BAR
        if bar.quote_cutoff_seq < bar.last_ingest_seq:
            return BarBarrierReason.BLOCKED_QUOTE_CUTOFF
        return None

    @staticmethod
    def _metadata_mismatch(first: BarEvidence, current: BarEvidence) -> Optional[str]:
        for field_name, reason in (
            ("bucket_start", BarBarrierReason.BUCKET_MISMATCH),
            ("bucket_end", BarBarrierReason.BUCKET_MISMATCH),
            ("trading_day", BarBarrierReason.TRADING_DAY_MISMATCH),
            ("generation", BarBarrierReason.GENERATION_MISMATCH),
            ("session_segment", BarBarrierReason.SESSION_MISMATCH),
            ("rules_hash", BarBarrierReason.RULES_HASH_MISMATCH),
            ("clock_domain", BarBarrierReason.CLOCK_DOMAIN_MISMATCH),
            ("clock_mode", BarBarrierReason.CLOCK_MODE_MISMATCH),
            ("clock_mapping", BarBarrierReason.CLOCK_MAPPING_MISMATCH),
        ):
            if getattr(first, field_name) != getattr(current, field_name):
                return reason
        return None

    def _result(
        self,
        reason: str,
        *,
        key: Optional[Tuple[Any, ...]] = None,
        reset_warmup: bool = False,
        decision_input: Optional[MinuteDecisionInput] = None,
    ) -> BarBarrierResult:
        result = BarBarrierResult(
            reason=reason,
            decision_input=decision_input,
            key=key,
            reset_warmup=reset_warmup,
        )
        self._last_results.append(result)
        return result

    def _mark_skipped(self, key: Tuple[Any, ...], reason: str) -> BarBarrierResult:
        self._skipped[key] = reason
        self._skipped.move_to_end(key)
        while len(self._skipped) > self._MAX_RETAINED_INPUTS:
            self._skipped.popitem(last=False)
        bucket_end = key[5]
        self._record_bucket_watermark(bucket_end)
        self._pending.pop(key, None)
        self._pending_core = {
            core: value for core, value in self._pending_core.items() if value != key
        }
        self._retire_pending_through(bucket_end)
        return self._result(reason, key=key, reset_warmup=True)

    def _retire_pending_through(self, bucket_end: datetime) -> None:
        """Drop older incomplete buckets while retaining only a bounded tombstone cache."""

        for pending_key in list(self._pending):
            if pending_key[5] > bucket_end:
                continue
            self._pending.pop(pending_key, None)
            self._skipped[pending_key] = BarBarrierReason.LATE_BAR_REJECTED
            self._skipped.move_to_end(pending_key)
        self._pending_core = {
            core: value for core, value in self._pending_core.items() if value in self._pending
        }
        while len(self._skipped) > self._MAX_RETAINED_INPUTS:
            self._skipped.popitem(last=False)

    def _invalidate_scope(self, reason: str) -> Tuple[BarBarrierResult, ...]:
        """Retire every pending bucket after a scope or clock fault."""

        results = []
        pending_keys = list(self._pending)
        self._latch_scope_fault(reason)
        for key in pending_keys:
            results.append(self._mark_skipped(key, reason))
        return tuple(results)

    def _mapping_for(self, pending: Mapping[str, Any]) -> ClockMapping:
        bars = pending["bars"]
        return next(iter(bars.values())).clock_mapping

    def _mapped_available_mono(self, pending: Mapping[str, Any]) -> float:
        mapping = self._mapping_for(pending)
        mapped = []
        for bar in pending["bars"].values():
            if bar.clock_mapping != mapping:
                raise ValueError("bars use different clock mappings")
            mapped_ns = mapping.map_wall_to_mono_ns(bar.available_at)
            if mapped_ns + mapping.error_bound_ns > mapping.valid_until_mono_ns:
                raise ValueError("clock mapping is expired before bar availability")
            # Readiness uses the latest mapped instant in the known error
            # interval, so a small mapping uncertainty cannot yield early data.
            mapped.append((mapped_ns + mapping.error_bound_ns) / 1_000_000_000.0)
        return max(mapped)

    def _finalize_pending(
        self, key: Tuple[Any, ...], pending: Mapping[str, Any]
    ) -> BarBarrierResult:
        decision = self._freeze_input(key, pending)
        skew_reason = self._cross_leg_quote_skew(decision)
        if skew_reason is not None:
            return self._mark_skipped(key, skew_reason)
        self._pending.pop(key, None)
        self._pending_core.pop(self._core(next(iter(pending["bars"].values()))), None)
        self._finalized[key] = decision
        self._finalized.move_to_end(key)
        while len(self._finalized) > self._MAX_RETAINED_INPUTS:
            self._finalized.popitem(last=False)
        bucket_end = key[5]
        self._record_bucket_watermark(bucket_end)
        self._retire_pending_through(bucket_end)
        self._last_input = decision
        return self._result(BarBarrierReason.READY, key=key, decision_input=decision)

    def ingest(self, bar: Any, *, now_mono: Any = None, now: Any = None) -> BarBarrierResult:
        """Ingest one feed-created bar without consulting a process clock."""

        if not isinstance(bar, BarEvidence):
            try:
                bar = BarEvidence(
                    symbol=_alias(bar, "symbol", "instrument_id", "InstrumentID"),
                    exchange=_alias(bar, "exchange", "exchange_id", "ExchangeID"),
                    bucket_start=_alias(bar, "bucket_start", "start"),
                    bucket_end=_alias(bar, "bucket_end", "end"),
                    available_at=_alias(bar, "available_at", "bar_available_at"),
                    seal_received_mono=_bar_seal_monotonic(bar),
                    trading_day=_alias(bar, "trading_day", "TradingDay", default=_MISSING),
                    generation=_alias(bar, "generation", "connection_generation", default=_MISSING),
                    session_segment=_alias(bar, "session_segment", "session", default=_MISSING),
                    rules_hash=_alias(bar, "rules_hash", default=_MISSING),
                    quality=_alias(bar, "quality", default=_MISSING),
                    volume_complete=_alias(bar, "volume_complete", default=_MISSING),
                    first_ingest_seq=_alias(bar, "first_ingest_seq", default=0),
                    last_ingest_seq=_alias(bar, "last_ingest_seq", default=0),
                    quote_cutoff_seq=_alias(bar, "quote_cutoff_seq", default=_MISSING),
                    bar_id=_alias(bar, "bar_id", default=""),
                    bar_sequence=_alias(bar, "bar_sequence", default=0),
                    closure_reason=_alias(bar, "closure_reason", default="watermark"),
                    watermark=_alias(bar, "watermark", "event_watermark", default=None),
                    max_event_time=_alias(bar, "max_event_time", default=None),
                    open=_alias(bar, "open", default=0.0),
                    high=_alias(bar, "high", default=0.0),
                    low=_alias(bar, "low", default=0.0),
                    close=_alias(bar, "close", default=0.0),
                    volume=_alias(bar, "volume", default=0.0),
                    openinterest=_alias(bar, "openinterest", default=0.0),
                    quote_events=_alias(bar, "quote_events", "quotes", default=()),
                    clock_domain=_alias(bar, "clock_domain", "clock_domain_id", default=_MISSING),
                    clock_mode=_alias(bar, "clock_mode", default=_MISSING),
                    seal_received_at=_alias(
                        bar, "seal_received_at", "received_at", default=_MISSING
                    ),
                    candidate_id=_alias(bar, "candidate_id", default=""),
                    timeframe_seconds=_alias(bar, "timeframe_seconds", default=None),
                    trade_count=_alias(bar, "trade_count", default=None),
                    complete=_alias(bar, "complete", default=_MISSING),
                    clock_mapping=_alias(bar, "clock_mapping", default=_MISSING),
                )
            except (TypeError, ValueError, KeyError):
                return self._result(BarBarrierReason.INVALID_BAR, reset_warmup=True)

        if now_mono is not None and now is not None:
            try:
                parsed_now = _mono(now_mono, "now_mono")
                parsed_alias = _mono(now, "now")
            except ValueError:
                results = self._invalidate_scope(BarBarrierReason.CLOCK_INVALID)
                return (
                    results[-1]
                    if results
                    else self._result(BarBarrierReason.CLOCK_INVALID, reset_warmup=True)
                )
            if parsed_now != parsed_alias:
                results = self._invalidate_scope(BarBarrierReason.CLOCK_INVALID)
                return (
                    results[-1]
                    if results
                    else self._result(BarBarrierReason.CLOCK_INVALID, reset_warmup=True)
                )
            now_mono = parsed_now
        elif now_mono is None:
            now_mono = now
        observed_now: Optional[float] = None
        if now_mono is not None:
            try:
                observed_now = _mono(now_mono, "now_mono")
            except ValueError:
                results = self._invalidate_scope(BarBarrierReason.CLOCK_INVALID)
                return (
                    results[-1]
                    if results
                    else self._result(BarBarrierReason.CLOCK_INVALID, reset_warmup=True)
                )
            clock_results = self.advance(observed_now)
            if clock_results and clock_results[-1].reason in {
                BarBarrierReason.CLOCK_REGRESSION,
                BarBarrierReason.CLOCK_INVALID,
            }:
                return clock_results[-1]

        key = self._key(bar)
        core = self._core(bar)
        existing_core_key = self._pending_core.get(core)
        existing_pending = self._pending.get(existing_core_key) if existing_core_key else None
        # A leg that arrives after the first-seal deadline is permanently
        # late even when its metadata was reconstructed with a fresh mapping.
        # Evaluate this absolute deadline before scope diagnostics so a late
        # leg cannot alter the result into a new-scope path.
        if (
            existing_pending is not None
            and bar.seal_received_mono > existing_pending["deadline_mono"]
        ):
            return self._mark_skipped(existing_core_key, BarBarrierReason.SKIP_BARRIER_TIMEOUT)
        identity_reason = self._identity_reason(bar, key)
        if identity_reason is not None:
            existing_key = self._pending_core.get(core)
            if existing_key is not None and identity_reason in {
                BarBarrierReason.BUCKET_MISMATCH,
                BarBarrierReason.TRADING_DAY_MISMATCH,
                BarBarrierReason.GENERATION_MISMATCH,
                BarBarrierReason.SESSION_MISMATCH,
                BarBarrierReason.RULES_HASH_MISMATCH,
                BarBarrierReason.CLOCK_DOMAIN_MISMATCH,
                BarBarrierReason.CLOCK_MODE_MISMATCH,
                BarBarrierReason.CLOCK_MAPPING_MISMATCH,
            }:
                self._mark_skipped(existing_key, identity_reason)
                self._latch_scope_fault(identity_reason)
            elif self._scope is not None and identity_reason in {
                BarBarrierReason.CANDIDATE_MISMATCH,
                BarBarrierReason.TRADING_DAY_MISMATCH,
                BarBarrierReason.GENERATION_MISMATCH,
                BarBarrierReason.SESSION_MISMATCH,
                BarBarrierReason.RULES_HASH_MISMATCH,
                BarBarrierReason.CLOCK_DOMAIN_MISMATCH,
                BarBarrierReason.CLOCK_MODE_MISMATCH,
                BarBarrierReason.CLOCK_MAPPING_MISMATCH,
            }:
                # A completed bucket has no pending key to invalidate, but a
                # scope change still retires the old lifecycle globally.
                self._latch_scope_fault(identity_reason)
            return self._result(identity_reason, key=key, reset_warmup=True)
        if self._clock_fault is not None:
            return self._result(self._clock_fault, key=key, reset_warmup=True)
        if self._retired_bucket_end is not None and bar.bucket_end <= self._retired_bucket_end:
            return self._result(BarBarrierReason.LATE_BAR_REJECTED, key=key)
        if self._last_now_mono is not None and bar.seal_received_mono < self._last_now_mono:
            self._latch_scope_fault(BarBarrierReason.CLOCK_REGRESSION)
            return self._mark_skipped(key, BarBarrierReason.CLOCK_REGRESSION)
        if observed_now is not None and bar.seal_received_mono > observed_now:
            return self._mark_skipped(key, BarBarrierReason.FUTURE_SEAL_REJECTED)
        # A seal is itself an observation in the barrier's monotonic domain.
        # Record it before quality/payload processing so a malformed or
        # incomplete bar cannot make a later earlier seal look admissible.
        self._observe_seal(bar.seal_received_mono)
        bar_reason = self._bar_reason(bar)
        if bar_reason is not None:
            return self._mark_skipped(key, bar_reason)
        if self._scope is None:
            self._scope = self._scope_for(bar)
            self._record_scope_lifecycle(self._scope)

        core = self._core(bar)
        existing_key = self._pending_core.get(core)
        if existing_key is not None and existing_key != key:
            first_pending = self._pending.get(existing_key)
            first_bar = next(iter(first_pending["bars"].values())) if first_pending else None
            if first_bar is not None:
                mismatch = self._metadata_mismatch(first_bar, bar)
                if mismatch is not None:
                    self._mark_skipped(existing_key, mismatch)
                    self._latch_scope_fault(mismatch)
                    return self._result(mismatch, key=key, reset_warmup=True)
            self._mark_skipped(existing_key, BarBarrierReason.BUCKET_MISMATCH)
            self._latch_scope_fault(BarBarrierReason.BUCKET_MISMATCH)
            return self._result(BarBarrierReason.BUCKET_MISMATCH, key=key, reset_warmup=True)

        pending = self._pending.get(key)
        if pending is not None:
            if bar.symbol in pending["bars"]:
                prior = pending["bars"][bar.symbol]
                reason = (
                    BarBarrierReason.DUPLICATE_BAR
                    if prior.bar_id == bar.bar_id
                    else BarBarrierReason.REVISION_REJECTED
                )
                return self._result(reason, key=key)
            if bar.seal_received_mono > pending["deadline_mono"]:
                return self._mark_skipped(key, BarBarrierReason.SKIP_BARRIER_TIMEOUT)
            first_bar = next(iter(pending["bars"].values()))
            mismatch = self._metadata_mismatch(first_bar, bar)
            if mismatch is not None:
                self._mark_skipped(key, mismatch)
                self._latch_scope_fault(mismatch)
                return self._result(mismatch, key=key, reset_warmup=True)
            if bar.seal_received_mono < pending["last_seal_mono"]:
                self._latch_scope_fault(BarBarrierReason.CLOCK_REGRESSION)
                return self._mark_skipped(key, BarBarrierReason.CLOCK_REGRESSION)
            if bar.seal_received_at < pending["last_seal_at"]:
                self._latch_scope_fault(BarBarrierReason.CLOCK_REGRESSION)
                return self._mark_skipped(key, BarBarrierReason.CLOCK_REGRESSION)
        else:
            if len(self._pending) >= self._MAX_PENDING_BUCKETS:
                oldest_key = min(self._pending, key=lambda pending_key: pending_key[5])
                self._mark_skipped(oldest_key, BarBarrierReason.SKIP_BARRIER_TIMEOUT)
            mapping = bar.clock_mapping
            try:
                mapped_hard_deadline = mapping.conservative_deadline_seconds(
                    bar.bucket_end + timedelta(seconds=self.policy.timeout_seconds)
                )
            except ValueError:
                return self._mark_skipped(key, BarBarrierReason.CLOCK_MAPPING_MISMATCH)
            deadline = min(
                bar.seal_received_mono + self.policy.timeout_seconds,
                mapped_hard_deadline,
            )
            if deadline < bar.seal_received_mono:
                return self._mark_skipped(key, BarBarrierReason.SKIP_BARRIER_TIMEOUT)
            pending = {
                "bars": {},
                "first_seal_mono": bar.seal_received_mono,
                "deadline_mono": deadline,
                "clock_domain": bar.clock_domain,
                "clock_mode": bar.clock_mode,
                "clock_mapping": mapping,
                "last_seal_mono": bar.seal_received_mono,
                "last_seal_at": bar.seal_received_at,
                "complete": False,
            }
            self._pending[key] = pending
            self._pending_core[core] = key
        pending["bars"][bar.symbol] = bar
        pending["last_seal_mono"] = max(pending["last_seal_mono"], bar.seal_received_mono)
        pending["last_seal_at"] = max(pending["last_seal_at"], bar.seal_received_at)
        if len(pending["bars"]) < len(self.expected_legs):
            return self._result(BarBarrierReason.WAITING_FOR_LEGS, key=key)

        try:
            common_available_mono = self._mapped_available_mono(pending)
        except ValueError:
            return self._mark_skipped(key, BarBarrierReason.CLOCK_MAPPING_MISMATCH)
        pending["common_available_mono"] = common_available_mono
        pending["complete"] = True
        arrival_mono = max(bar.seal_received_mono for bar in pending["bars"].values())
        observed = arrival_mono if observed_now is None else observed_now
        if observed < common_available_mono:
            return self._result(BarBarrierReason.WAITING_FOR_WATERMARK, key=key)
        if observed > pending["deadline_mono"]:
            return self._mark_skipped(key, BarBarrierReason.SKIP_BARRIER_TIMEOUT)
        pending["ready_mono"] = max(arrival_mono, common_available_mono)
        return self._finalize_pending(key, pending)

    def _cross_leg_quote_skew(self, decision: MinuteDecisionInput) -> Optional[str]:
        """Reject a complete quote cohort whose source or receive times skew."""

        latest_source = []
        latest_receive = []
        for symbol in (leg.symbol for leg in self.expected_legs):
            events = decision.accepted_quotes.get(symbol, ())
            if not events:
                return None
            latest = max(
                events, key=lambda event: _datetime(event["event_time"], "quote.event_time")
            )
            latest_source.append(_datetime(latest["event_time"], "quote.event_time"))
            latest_receive.append(_datetime(latest["received_at"], "quote.received_at"))
        source_skew_ms = (max(latest_source) - min(latest_source)).total_seconds() * 1000.0
        receive_skew_ms = (max(latest_receive) - min(latest_receive)).total_seconds() * 1000.0
        if max(source_skew_ms, receive_skew_ms) > self.policy.max_quote_skew_ms:
            return BarBarrierReason.BLOCKED_CROSS_LEG_SKEW
        return None

    def _freeze_input(
        self, key: Tuple[Any, ...], pending: Mapping[str, Any]
    ) -> MinuteDecisionInput:
        bars = pending["bars"]
        ordered = {leg.symbol: bars[leg.symbol] for leg in self.expected_legs}
        seals = [bar.seal_received_mono for bar in ordered.values()]
        available = max(bar.available_at for bar in ordered.values())
        accepted: Dict[str, Tuple[Mapping[str, Any], ...]] = {}
        rejected: Dict[str, Tuple[str, ...]] = {}
        quality: Dict[str, Any] = {}
        for symbol, bar in ordered.items():
            valid_events = []
            reasons = []
            seen_sequences = set()
            for event in bar.quote_events:
                result = _quote_filter(event, bar=bar, max_skew_ms=self.policy.max_quote_skew_ms)
                if result.accepted and result.event is not None:
                    sequence = result.event["ingest_seq"]
                    if sequence in seen_sequences:
                        reasons.append(BarBarrierReason.QUOTE_DUPLICATE)
                        continue
                    seen_sequences.add(sequence)
                    valid_events.append(result.event)
                else:
                    reasons.append(result.reason)
            accepted[symbol] = tuple(valid_events)
            rejected[symbol] = tuple(reasons)
            quality[symbol] = {
                "bar_quality": bar.quality,
                "volume_complete": bar.volume_complete,
                "quote_cutoff_seq": bar.quote_cutoff_seq,
                "quote_rejections": tuple(reasons),
            }
        # ``_metadata_mismatch`` has already guaranteed same scope, so the
        # common key is safe to expose and suitable for a deterministic hash.
        return MinuteDecisionInput(
            key=key,
            bars=ordered,
            bucket_start=next(iter(ordered.values())).bucket_start,
            bucket_end=next(iter(ordered.values())).bucket_end,
            common_available_at=available,
            bar_ids=tuple(bar.bar_id for bar in ordered.values()),
            quote_cutoffs={symbol: bar.quote_cutoff_seq for symbol, bar in ordered.items()},
            accepted_quotes=accepted,
            quote_rejections=rejected,
            source_sequences={
                symbol: (bar.first_ingest_seq, bar.last_ingest_seq)
                for symbol, bar in ordered.items()
            },
            quality_report=quality,
            trading_day=next(iter(ordered.values())).trading_day,
            generation=next(iter(ordered.values())).generation,
            session_segment=next(iter(ordered.values())).session_segment,
            rules_hash=next(iter(ordered.values())).rules_hash,
            candidate_id=key[0],
            clock_domain=next(iter(ordered.values())).clock_domain,
            clock_mode=next(iter(ordered.values())).clock_mode,
            barrier_ready_mono=pending.get("ready_mono", max(seals)),
            deadline_mono=pending["deadline_mono"],
            clock_mapping=next(iter(ordered.values())).clock_mapping,
        )

    def advance(self, now_mono: Any) -> Tuple[BarBarrierResult, ...]:
        """Expire pending buckets using an explicit replay/live monotonic time."""

        try:
            now = _mono(now_mono, "now_mono")
        except ValueError:
            return self._invalidate_scope(BarBarrierReason.CLOCK_INVALID) or (
                self._result(BarBarrierReason.CLOCK_INVALID, reset_warmup=True),
            )
        if self._clock_fault is not None:
            return (self._result(self._clock_fault, reset_warmup=True),)
        if self._last_now_mono is not None and now < self._last_now_mono:
            results = self._invalidate_scope(BarBarrierReason.CLOCK_REGRESSION)
            return results or (self._result(BarBarrierReason.CLOCK_REGRESSION, reset_warmup=True),)
        self._last_now_mono = now
        results = []
        for key, pending in list(self._pending.items()):
            if now > pending["deadline_mono"]:
                results.append(self._mark_skipped(key, BarBarrierReason.SKIP_BARRIER_TIMEOUT))
            elif pending.get("complete") and now >= pending["common_available_mono"]:
                pending["ready_mono"] = max(
                    pending["common_available_mono"],
                    max(bar.seal_received_mono for bar in pending["bars"].values()),
                )
                results.append(self._finalize_pending(key, pending))
        return tuple(results)

    def accept_quote(
        self, event: Any, *, decision_input: Optional[MinuteDecisionInput] = None
    ) -> QuoteCutoffResult:
        """Check a quote against an already-frozen input without mutating it.

        A quote arriving after seal can be inspected for diagnostics, but it
        cannot be admitted into the stored input.  This is the key protection
        against a mutable ``latest_quote`` becoming a historical feature.
        """

        if self._clock_fault is not None:
            return QuoteCutoffResult(
                False,
                self._clock_fault,
                symbol=_value(event, "symbol", "instrument_id", "InstrumentID"),
            )
        if decision_input is not None:
            decision_scope = self._scope_from_values(
                decision_input.candidate_id,
                decision_input.trading_day,
                decision_input.generation,
                decision_input.session_segment,
                decision_input.rules_hash,
                decision_input.clock_domain,
                decision_input.clock_mode,
                decision_input.clock_mapping,
            )
            if self._scope is None or decision_scope != self._scope:
                return QuoteCutoffResult(
                    False,
                    BarBarrierReason.SCOPE_RESET_REQUIRED,
                    symbol=_value(event, "symbol", "instrument_id", "InstrumentID"),
                )
            # A matching scope is necessary but not sufficient.  The object
            # must still be one of this barrier's bounded finalized records;
            # after reset or finalized-cache eviction, an old immutable
            # decision remains audit data and cannot regain quote authority.
            if self._finalized.get(decision_input.key) is not decision_input:
                return QuoteCutoffResult(
                    False,
                    BarBarrierReason.SCOPE_RESET_REQUIRED,
                    symbol=_value(event, "symbol", "instrument_id", "InstrumentID"),
                )
        target = decision_input or self._last_input
        if target is None:
            return QuoteCutoffResult(False, BarBarrierReason.NO_FROZEN_INPUT)
        symbol = _value(event, "symbol", "instrument_id", "InstrumentID")
        bar = target.bars.get(symbol)
        if bar is None:
            return QuoteCutoffResult(False, BarBarrierReason.QUOTE_SCOPE_MISMATCH, symbol=symbol)
        result = _quote_filter(event, bar=bar, max_skew_ms=self.policy.max_quote_skew_ms)
        if not result.accepted:
            return result
        for existing in target.accepted_quotes.get(symbol, ()):
            if existing.get("ingest_seq") == result.event.get("ingest_seq"):
                if existing == result.event:
                    return QuoteCutoffResult(
                        True,
                        BarBarrierReason.READY,
                        symbol=symbol,
                        event=existing,
                    )
                return QuoteCutoffResult(
                    False,
                    BarBarrierReason.QUOTE_IDENTITY_CONFLICT,
                    symbol=symbol,
                    event=existing,
                )
        return QuoteCutoffResult(
            False,
            BarBarrierReason.QUOTE_NOT_IN_FROZEN_INPUT,
            symbol=symbol,
        )


__all__ = [
    "BarBarrierPolicy",
    "BarBarrierReason",
    "BarBarrierResult",
    "BarEvidence",
    "BarLeg",
    "ClockMapping",
    "MinuteDecisionInput",
    "MultiLegBarBarrier",
    "QuoteCutoffResult",
    "validate_quote_against_bar",
]
