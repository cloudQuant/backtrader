"""Strict, side-effect-free CTP multi-leg quote cohort validation.

This module turns public ``ctp.quote.v2`` snapshots into immutable evidence
objects and admits a cohort only after every configured leg has supplied a
new, valid quote.  It deliberately has no network, order, broker, or strategy
dependency: a caller may use an admitted cohort for a screen, a bar decision,
or an observation-only audit, but this module never creates an order or an
execution intent.

The validator treats source-time quality as an explicit prerequisite.  A
missing or unverified source clock is rejected; it is never upgraded from a
receive timestamp or a local fallback clock.
"""

from __future__ import annotations

import math
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from types import MappingProxyType
from typing import Any, Optional, Tuple

_MAX_ABS_NUMBER = 1.0e30
_MAX_UINT64 = (1 << 64) - 1
_PROVENANCE_PLACEHOLDERS = frozenset(
    {
        "unknown",
        "unverified",
        "n/a",
        "na",
        "none",
        "null",
        "unset",
        "placeholder",
    }
)


class CtpCohortReason:
    """Stable reasons returned by :class:`CtpQuoteCohortValidator`.

    A successful result has ``reason is None``.  These string constants are
    intentionally public so strategy logs and tests do not need to parse an
    exception message.
    """

    WAITING_FOR_LEGS = "WAITING_FOR_LEGS"
    WAITING_FOR_ALL_LEGS_NEW = "WAITING_FOR_ALL_LEGS_NEW"
    UNEXPECTED_SYMBOL = "UNEXPECTED_SYMBOL"
    QUOTE_SYMBOL_MISSING = "QUOTE_SYMBOL_MISSING"
    QUOTE_IDENTITY_CONFLICT = "QUOTE_IDENTITY_CONFLICT"
    EXCHANGE_MISMATCH = "EXCHANGE_MISMATCH"
    ASSET_TYPE_MISMATCH = "ASSET_TYPE_MISMATCH"
    UNSUPPORTED_QUOTE_SCHEMA = "UNSUPPORTED_QUOTE_SCHEMA"
    VOLUME_SEMANTICS_NOT_DELTA = "VOLUME_SEMANTICS_NOT_DELTA"
    SOURCE_CLOCK_UNVERIFIED = "SOURCE_CLOCK_UNVERIFIED"
    RECEIVE_CLOCK_UNVERIFIED = "RECEIVE_CLOCK_UNVERIFIED"
    FRESHNESS_UNVERIFIED = "FRESHNESS_UNVERIFIED"
    EVENT_TIME_SOURCE_MISSING = "EVENT_TIME_SOURCE_MISSING"
    RULES_HASH_MISMATCH = "RULES_HASH_MISMATCH"
    QUOTE_SOURCE_MISSING = "QUOTE_SOURCE_MISSING"
    QUOTE_STREAM_UNREADY = "QUOTE_STREAM_UNREADY"
    QUOTE_CONTINUITY_NOT_CONTINUOUS = "QUOTE_CONTINUITY_NOT_CONTINUOUS"
    QUOTE_QUALITY_FLAGS_INVALID = "QUOTE_QUALITY_FLAGS_INVALID"
    QUOTE_QUALITY_FLAGS_PRESENT = "QUOTE_QUALITY_FLAGS_PRESENT"
    EXECUTION_INELIGIBLE_QUOTE = "EXECUTION_INELIGIBLE_QUOTE"
    VOLUME_INCOMPLETE = "VOLUME_INCOMPLETE"
    VOLUME_QUALITY_NOT_CONTINUOUS = "VOLUME_QUALITY_NOT_CONTINUOUS"
    QUOTE_NUMERIC_TYPE_INVALID = "QUOTE_NUMERIC_TYPE_INVALID"
    QUOTE_NUMERIC_INVALID = "QUOTE_NUMERIC_INVALID"
    QUOTE_NONPOSITIVE = "QUOTE_NONPOSITIVE"
    QUOTE_CROSSED = "QUOTE_CROSSED"
    DAILY_PRICE_LIMIT_INVALID = "DAILY_PRICE_LIMIT_INVALID"
    QUOTE_OUTSIDE_DAILY_LIMIT = "QUOTE_OUTSIDE_DAILY_LIMIT"
    QUOTE_OFF_TICK_GRID = "QUOTE_OFF_TICK_GRID"
    QUOTE_IDENTITY_TYPE_INVALID = "QUOTE_IDENTITY_TYPE_INVALID"
    QUOTE_IDENTITY_OR_CLOCK_MISSING = "QUOTE_IDENTITY_OR_CLOCK_MISSING"
    TRADING_DAY_INVALID = "TRADING_DAY_INVALID"
    ACTION_DAY_INVALID = "ACTION_DAY_INVALID"
    CLOCK_DOMAIN_UNKNOWN = "CLOCK_DOMAIN_UNKNOWN"
    SOURCE_TIME_INVALID = "SOURCE_TIME_INVALID"
    RECEIVE_TIME_INVALID = "RECEIVE_TIME_INVALID"
    SOURCE_TIME_AFTER_RECEIVE = "SOURCE_TIME_AFTER_RECEIVE"
    SOURCE_CLOCK_ERROR_INVALID = "SOURCE_CLOCK_ERROR_INVALID"
    RECEIVE_CLOCK_ERROR_INVALID = "RECEIVE_CLOCK_ERROR_INVALID"
    DUPLICATE_OR_OUT_OF_ORDER = "DUPLICATE_OR_OUT_OF_ORDER"
    OUT_OF_ORDER_RECEIVE_TIME = "OUT_OF_ORDER_RECEIVE_TIME"
    OUT_OF_ORDER_SOURCE_TIME = "OUT_OF_ORDER_SOURCE_TIME"
    COHORT_EXCHANGE_MISMATCH = "COHORT_EXCHANGE_MISMATCH"
    COHORT_TRADING_DAY_MISMATCH = "COHORT_TRADING_DAY_MISMATCH"
    COHORT_ACTION_DAY_MISMATCH = "COHORT_ACTION_DAY_MISMATCH"
    COHORT_CONNECTION_GENERATION_MISMATCH = "COHORT_CONNECTION_GENERATION_MISMATCH"
    COHORT_SUBSCRIPTION_EPOCH_MISMATCH = "COHORT_SUBSCRIPTION_EPOCH_MISMATCH"
    COHORT_RULES_HASH_MISMATCH = "COHORT_RULES_HASH_MISMATCH"
    COHORT_CLOCK_DOMAIN_MISMATCH = "COHORT_CLOCK_DOMAIN_MISMATCH"
    STALE_COHORT_RECEIVE_TIME = "STALE_COHORT_RECEIVE_TIME"
    BLOCKED_CROSS_LEG_SKEW = "BLOCKED_CROSS_LEG_SKEW"
    STALE_COHORT_SOURCE_TIME = "STALE_COHORT_SOURCE_TIME"
    BLOCKED_SOURCE_SKEW = "BLOCKED_SOURCE_SKEW"
    TRUSTED_NOW_REQUIRED = "TRUSTED_NOW_REQUIRED"
    TRUSTED_NOW_INVALID = "TRUSTED_NOW_INVALID"
    NOW_CLOCK_DOMAIN_MISMATCH = "NOW_CLOCK_DOMAIN_MISMATCH"
    NOW_WALL_TIME_BEFORE_QUOTE = "NOW_WALL_TIME_BEFORE_QUOTE"
    RETIRED_CONNECTION_SCOPE = "RETIRED_CONNECTION_SCOPE"
    NO_CONFIRMED_COHORT = "NO_CONFIRMED_COHORT"


def _strict_positive_number(value: Any, *, field: str) -> float:
    """Return a finite positive built-in numeric value or raise ``ValueError``."""

    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{field} must be a built-in finite positive number")
    number = float(value)
    if not math.isfinite(number) or number <= 0.0 or abs(number) >= _MAX_ABS_NUMBER:
        raise ValueError(f"{field} must be a built-in finite positive number")
    return number


def _strict_nonnegative_number(value: Any, *, field: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{field} must be a built-in finite non-negative number")
    number = float(value)
    if not math.isfinite(number) or number < 0.0 or abs(number) >= _MAX_ABS_NUMBER:
        raise ValueError(f"{field} must be a built-in finite non-negative number")
    return number


def _strict_nonempty_text(value: Any, *, field: str) -> str:
    if not isinstance(value, str) or not value or value.strip() != value:
        raise ValueError(f"{field} must be a non-empty string")
    return value


def _is_strict_nonempty_text(value: Any) -> bool:
    return isinstance(value, str) and bool(value) and value.strip() == value


def _is_provenance_identity(value: Any) -> bool:
    """Accept an explicit provenance identity, never a placeholder value.

    CTP quote fields such as source, rules hash and clock domain are security
    boundaries.  Treating a literal ``"unknown"`` as an identity would let a
    caller make two unrelated unknown values appear to match.
    """

    return _is_strict_nonempty_text(value) and value.casefold() not in _PROVENANCE_PLACEHOLDERS


def _strict_provenance_identity(value: Any, *, field: str) -> str:
    if not _is_provenance_identity(value):
        raise ValueError(f"{field} must be a non-placeholder provenance identity")
    return value


@dataclass(frozen=True)
class CtpCohortLeg:
    """One immutable expected leg in a two- or three-leg CTP cohort."""

    symbol: str
    exchange: str
    price_tick: float
    asset_type: Optional[str] = None

    def __post_init__(self) -> None:
        _strict_nonempty_text(self.symbol, field="symbol")
        _strict_nonempty_text(self.exchange, field="exchange")
        object.__setattr__(
            self,
            "price_tick",
            _strict_positive_number(self.price_tick, field="price_tick"),
        )
        if self.asset_type is not None:
            if self.asset_type not in {"future", "option"}:
                raise ValueError("asset_type must be future, option, or None")


@dataclass(frozen=True)
class CtpCohortPolicy:
    """Immutable time-quality bounds for a cohort decision."""

    max_receive_age_ms: float
    max_receive_skew_ms: float
    max_source_age_ms: float
    max_source_skew_ms: float
    max_source_clock_error_ms: float
    max_receive_clock_error_ms: float

    def __post_init__(self) -> None:
        for name in (
            "max_receive_age_ms",
            "max_receive_skew_ms",
            "max_source_age_ms",
            "max_source_skew_ms",
            "max_source_clock_error_ms",
            "max_receive_clock_error_ms",
        ):
            object.__setattr__(
                self,
                name,
                _strict_nonnegative_number(getattr(self, name), field=name),
            )


@dataclass(frozen=True)
class CtpCohortNow:
    """Trusted current-time evidence supplied by a cohort caller.

    The validator intentionally does not call a process clock.  A caller must
    provide a same-domain monotonic reading and a verified receive-wall-clock
    reading for every ingestion and pre-submit recheck.  This makes queue
    delays observable instead of silently treating the most recent quote as
    ``now``.
    """

    now_monotonic_ns: int
    now_epoch: float
    clock_domain_id: str
    receive_clock_error_ms: float
    receive_clock_quality: str = "verified"
    freshness_verified: bool = True

    def __post_init__(self) -> None:
        monotonic = _strict_positive_uint64(self.now_monotonic_ns)
        epoch = _epoch_seconds(self.now_epoch)
        if monotonic is None or epoch is None:
            raise ValueError("now_monotonic_ns and now_epoch must be valid trusted clock values")
        _strict_provenance_identity(self.clock_domain_id, field="clock_domain_id")
        if self.receive_clock_quality != "verified":
            raise ValueError("receive_clock_quality must be verified")
        if self.freshness_verified is not True:
            raise ValueError("freshness_verified must be True")
        error = _strict_quote_number(self.receive_clock_error_ms)
        if error is None or error < 0.0:
            raise ValueError("receive_clock_error_ms must be a finite non-negative number")
        object.__setattr__(self, "now_monotonic_ns", monotonic)
        object.__setattr__(self, "now_epoch", epoch)
        object.__setattr__(self, "receive_clock_error_ms", error)


@dataclass(frozen=True)
class CtpQuoteEvidence:
    """Immutable validated CTP level-one quote evidence."""

    symbol: str
    exchange: str
    asset_type: Optional[str]
    bid: float
    ask: float
    bid_size: float
    ask_size: float
    last: float
    lower_limit: float
    upper_limit: float
    source_epoch: float
    receive_epoch: float
    receive_monotonic_ns: int
    ingest_seq: int
    connection_generation: int
    subscription_epoch: int
    trading_day: str
    action_day: str
    clock_domain_id: str
    rules_hash: str
    source: str
    event_time_source: str
    source_clock_error_ms: float
    receive_clock_error_ms: float

    @property
    def update_identity(self) -> Tuple[str, int, int, int]:
        """The immutable identity used to require a fresh quote per leg."""

        return (
            self.symbol,
            self.connection_generation,
            self.subscription_epoch,
            self.ingest_seq,
        )


@dataclass(frozen=True)
class CtpQuoteValidation:
    """The result of strict quote normalization without any state mutation."""

    quote: Optional[CtpQuoteEvidence]
    reason: Optional[str]

    @property
    def accepted(self) -> bool:
        return self.quote is not None


@dataclass(frozen=True)
class CtpQuoteCohort:
    """An immutable set of synchronized, fresh quote evidence."""

    quotes: Mapping[str, CtpQuoteEvidence]
    exchange: str
    trading_day: str
    action_day: str
    connection_generation: int
    subscription_epoch: int
    clock_domain_id: str
    rules_hash: str
    cohort_id: str

    def __post_init__(self) -> None:
        if not isinstance(self.quotes, Mapping) or not self.quotes:
            raise ValueError("quotes must be a non-empty mapping")
        quotes = dict(self.quotes)
        if not all(isinstance(quote, CtpQuoteEvidence) for quote in quotes.values()):
            raise TypeError("quotes must contain only CtpQuoteEvidence values")
        if any(symbol != quote.symbol for symbol, quote in quotes.items()):
            raise ValueError("quote mapping keys must exactly match quote.symbol")
        _strict_nonempty_text(self.exchange, field="exchange")
        if not _valid_trading_day(self.trading_day):
            raise ValueError("trading_day must be a valid YYYYMMDD date")
        if not _valid_trading_day(self.action_day):
            raise ValueError("action_day must be a valid YYYYMMDD date")
        if _strict_positive_uint64(self.connection_generation) is None:
            raise ValueError("connection_generation must be a positive uint64")
        if _strict_positive_uint64(self.subscription_epoch) is None:
            raise ValueError("subscription_epoch must be a positive uint64")
        _strict_provenance_identity(self.clock_domain_id, field="clock_domain_id")
        _strict_provenance_identity(self.rules_hash, field="rules_hash")
        _strict_nonempty_text(self.cohort_id, field="cohort_id")
        expected_metadata = {
            "exchange": self.exchange,
            "trading_day": self.trading_day,
            "action_day": self.action_day,
            "connection_generation": self.connection_generation,
            "subscription_epoch": self.subscription_epoch,
            "clock_domain_id": self.clock_domain_id,
            "rules_hash": self.rules_hash,
        }
        if any(
            any(getattr(quote, name) != value for name, value in expected_metadata.items())
            for quote in quotes.values()
        ):
            raise ValueError("cohort metadata must exactly match every quote")
        object.__setattr__(self, "quotes", MappingProxyType(quotes))

    def quote_for(self, symbol: str) -> CtpQuoteEvidence:
        """Return the evidence for an expected symbol."""

        return self.quotes[symbol]


@dataclass(frozen=True)
class CtpCohortResult:
    """The result of ingesting one quote into a stateful cohort validator."""

    cohort: Optional[CtpQuoteCohort]
    reason: Optional[str]

    @property
    def accepted(self) -> bool:
        return self.cohort is not None


def _event_value(event: Any, *names: str) -> Any:
    """Read the first present public field from a mapping or event object."""

    if isinstance(event, Mapping):
        for name in names:
            if name in event:
                return event[name]
        return None
    for name in names:
        if hasattr(event, name):
            return getattr(event, name)
    return None


def _consistent_identity_alias(event: Any, *names: str) -> Tuple[Any, bool]:
    """Read identity aliases and require every supplied spelling to agree."""

    values = []
    if isinstance(event, Mapping):
        for name in names:
            if name in event:
                values.append(event[name])
    else:
        for name in names:
            if hasattr(event, name):
                values.append(getattr(event, name))
    if not values:
        return None, True
    first = values[0]
    return first, all(value == first for value in values[1:])


def _strict_quote_number(value: Any) -> Optional[float]:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    number = float(value)
    if not math.isfinite(number) or abs(number) >= _MAX_ABS_NUMBER:
        return None
    return number


def _strict_positive_uint64(value: Any) -> Optional[int]:
    if type(value) is not int or value <= 0 or value > _MAX_UINT64:
        return None
    return value


def _epoch_seconds(value: Any) -> Optional[float]:
    """Parse only explicit, timezone-qualified wall-clock evidence."""

    if isinstance(value, bool):
        return None
    if isinstance(value, datetime):
        if value.tzinfo is None or value.utcoffset() is None:
            return None
        try:
            result = value.astimezone(timezone.utc).timestamp()
        except (OverflowError, OSError, ValueError):
            return None
    elif isinstance(value, (int, float)):
        result = float(value)
    elif isinstance(value, str):
        try:
            moment = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
        if moment.tzinfo is None or moment.utcoffset() is None:
            return None
        try:
            result = moment.astimezone(timezone.utc).timestamp()
        except (OverflowError, OSError, ValueError):
            return None
    else:
        return None
    if not math.isfinite(result) or abs(result) >= _MAX_ABS_NUMBER:
        return None
    return result


def _on_tick_grid(value: float, tick: float) -> bool:
    try:
        amount = Decimal(str(value))
        increment = Decimal(str(tick))
        return increment > 0 and amount.remainder_near(increment) == 0
    except (InvalidOperation, ValueError):
        return False


def _valid_trading_day(value: Any) -> bool:
    if not (isinstance(value, str) and len(value) == 8 and value.isascii() and value.isdecimal()):
        return False
    try:
        datetime.strptime(value, "%Y%m%d")
    except ValueError:
        return False
    return True


def _normalize_trusted_now(
    now: Any,
    *,
    policy: CtpCohortPolicy,
) -> Tuple[Optional[CtpCohortNow], Optional[str]]:
    """Return trusted caller time evidence without inventing clock facts."""

    if now is None:
        return None, CtpCohortReason.TRUSTED_NOW_REQUIRED
    if isinstance(now, CtpCohortNow):
        if now.receive_clock_error_ms > policy.max_receive_clock_error_ms:
            return None, CtpCohortReason.RECEIVE_CLOCK_ERROR_INVALID
        return now, None

    monotonic = _strict_positive_uint64(
        _event_value(now, "now_monotonic_ns", "recv_monotonic_ns", "received_monotonic_ns")
    )
    epoch = _epoch_seconds(
        _event_value(now, "now_epoch", "now_time_utc", "wall_time_utc", "recv_time_utc")
    )
    clock_domain_id = _event_value(now, "clock_domain_id")
    if monotonic is None or epoch is None or not _is_provenance_identity(clock_domain_id):
        return None, CtpCohortReason.TRUSTED_NOW_INVALID
    if _event_value(now, "receive_clock_quality") != "verified":
        return None, CtpCohortReason.RECEIVE_CLOCK_UNVERIFIED
    if _event_value(now, "freshness_verified") is not True:
        return None, CtpCohortReason.FRESHNESS_UNVERIFIED
    receive_clock_error_ms = _strict_quote_number(_event_value(now, "receive_clock_error_ms"))
    if (
        receive_clock_error_ms is None
        or receive_clock_error_ms < 0.0
        or receive_clock_error_ms > policy.max_receive_clock_error_ms
    ):
        return None, CtpCohortReason.RECEIVE_CLOCK_ERROR_INVALID
    return (
        CtpCohortNow(
            now_monotonic_ns=monotonic,
            now_epoch=epoch,
            clock_domain_id=clock_domain_id,
            receive_clock_error_ms=receive_clock_error_ms,
        ),
        None,
    )


def _scope_from_event(event: Any) -> Optional[Tuple[int, int]]:
    """Read a complete raw connection/subscription scope without coercion."""

    connection_generation = _strict_positive_uint64(_event_value(event, "connection_generation"))
    subscription_epoch = _strict_positive_uint64(_event_value(event, "subscription_epoch"))
    if connection_generation is None or subscription_epoch is None:
        return None
    return connection_generation, subscription_epoch


def validate_ctp_quote(
    event: Any,
    *,
    leg: CtpCohortLeg,
    expected_rules_hash: str,
    policy: CtpCohortPolicy,
) -> CtpQuoteValidation:
    """Normalize one ``ctp.quote.v2`` event into immutable evidence.

    The function does not retain the event and does not use system clocks.  In
    particular, a source timestamp is only usable after the producer explicitly
    labels its source clock ``verified``.
    """

    symbol, symbol_consistent = _consistent_identity_alias(
        event, "symbol", "instrument_id", "InstrumentID"
    )
    if not symbol_consistent:
        return CtpQuoteValidation(None, CtpCohortReason.QUOTE_IDENTITY_CONFLICT)
    if not isinstance(symbol, str) or not symbol:
        return CtpQuoteValidation(None, CtpCohortReason.QUOTE_SYMBOL_MISSING)
    if symbol != leg.symbol:
        return CtpQuoteValidation(None, CtpCohortReason.UNEXPECTED_SYMBOL)

    exchange, exchange_consistent = _consistent_identity_alias(
        event, "exchange", "exchange_id", "ExchangeID"
    )
    if not exchange_consistent:
        return CtpQuoteValidation(None, CtpCohortReason.QUOTE_IDENTITY_CONFLICT)
    if not isinstance(exchange, str) or exchange != leg.exchange:
        return CtpQuoteValidation(None, CtpCohortReason.EXCHANGE_MISMATCH)
    asset_type, asset_type_consistent = _consistent_identity_alias(
        event, "asset_type", "contract_type"
    )
    if not asset_type_consistent:
        return CtpQuoteValidation(None, CtpCohortReason.QUOTE_IDENTITY_CONFLICT)
    if leg.asset_type is not None and asset_type != leg.asset_type:
        return CtpQuoteValidation(None, CtpCohortReason.ASSET_TYPE_MISMATCH)
    if _event_value(event, "schema_version") != "ctp.quote.v2":
        return CtpQuoteValidation(None, CtpCohortReason.UNSUPPORTED_QUOTE_SCHEMA)
    if _event_value(event, "volume_semantics") != "delta":
        return CtpQuoteValidation(None, CtpCohortReason.VOLUME_SEMANTICS_NOT_DELTA)
    if _event_value(event, "source_clock_quality") != "verified":
        return CtpQuoteValidation(None, CtpCohortReason.SOURCE_CLOCK_UNVERIFIED)
    if _event_value(event, "receive_clock_quality") != "verified":
        return CtpQuoteValidation(None, CtpCohortReason.RECEIVE_CLOCK_UNVERIFIED)
    if _event_value(event, "freshness_verified") is not True:
        return CtpQuoteValidation(None, CtpCohortReason.FRESHNESS_UNVERIFIED)
    event_time_source = _event_value(event, "event_time_source")
    if not _is_provenance_identity(event_time_source):
        return CtpQuoteValidation(None, CtpCohortReason.EVENT_TIME_SOURCE_MISSING)
    rules_hash = _event_value(event, "rules_hash")
    if not _is_provenance_identity(rules_hash) or rules_hash != expected_rules_hash:
        return CtpQuoteValidation(None, CtpCohortReason.RULES_HASH_MISMATCH)
    source = _event_value(event, "source")
    if not _is_provenance_identity(source):
        return CtpQuoteValidation(None, CtpCohortReason.QUOTE_SOURCE_MISSING)
    if _event_value(event, "stale") is not False:
        return CtpQuoteValidation(None, CtpCohortReason.QUOTE_STREAM_UNREADY)
    if _event_value(event, "stale_reason") != "":
        return CtpQuoteValidation(None, CtpCohortReason.QUOTE_STREAM_UNREADY)
    if _event_value(event, "continuity_status") != "continuous":
        return CtpQuoteValidation(None, CtpCohortReason.QUOTE_CONTINUITY_NOT_CONTINUOUS)
    quality_flags = _event_value(event, "quality_flags")
    if not isinstance(quality_flags, (list, tuple, set, frozenset)):
        return CtpQuoteValidation(None, CtpCohortReason.QUOTE_QUALITY_FLAGS_INVALID)
    if quality_flags:
        return CtpQuoteValidation(None, CtpCohortReason.QUOTE_QUALITY_FLAGS_PRESENT)
    if _event_value(event, "execution_eligible") is not True:
        return CtpQuoteValidation(None, CtpCohortReason.EXECUTION_INELIGIBLE_QUOTE)
    if _event_value(event, "volume_complete") is not True:
        return CtpQuoteValidation(None, CtpCohortReason.VOLUME_INCOMPLETE)
    if _event_value(event, "volume_quality") != "CONTINUOUS":
        return CtpQuoteValidation(None, CtpCohortReason.VOLUME_QUALITY_NOT_CONTINUOUS)

    numeric_fields = {
        "bid": _event_value(event, "bid_price", "bid", "BidPrice1"),
        "ask": _event_value(event, "ask_price", "ask", "AskPrice1"),
        "bid_size": _event_value(event, "bid_volume", "bid_size", "BidVolume1"),
        "ask_size": _event_value(event, "ask_volume", "ask_size", "AskVolume1"),
        "last": _event_value(event, "price", "last_price", "last", "LastPrice"),
        "lower_limit": _event_value(
            event,
            "lower_limit_price",
            "lower_limit",
            "LowerLimitPrice",
        ),
        "upper_limit": _event_value(
            event,
            "upper_limit_price",
            "upper_limit",
            "UpperLimitPrice",
        ),
        "source_clock_error_ms": _event_value(event, "source_clock_error_ms"),
        "receive_clock_error_ms": _event_value(event, "receive_clock_error_ms"),
    }
    parsed: dict[str, float] = {}
    for name, value in numeric_fields.items():
        number = _strict_quote_number(value)
        if number is None:
            if name in {"source_clock_error_ms", "receive_clock_error_ms"}:
                reason = (
                    CtpCohortReason.SOURCE_CLOCK_ERROR_INVALID
                    if name == "source_clock_error_ms"
                    else CtpCohortReason.RECEIVE_CLOCK_ERROR_INVALID
                )
                return CtpQuoteValidation(None, reason)
            return CtpQuoteValidation(None, CtpCohortReason.QUOTE_NUMERIC_TYPE_INVALID)
        parsed[name] = number

    bid, ask, bid_size, ask_size, last = (
        parsed["bid"],
        parsed["ask"],
        parsed["bid_size"],
        parsed["ask_size"],
        parsed["last"],
    )
    lower_limit, upper_limit = parsed["lower_limit"], parsed["upper_limit"]
    source_clock_error_ms = parsed["source_clock_error_ms"]
    receive_clock_error_ms = parsed["receive_clock_error_ms"]
    if min(bid, ask, bid_size, ask_size, last) <= 0.0:
        return CtpQuoteValidation(None, CtpCohortReason.QUOTE_NONPOSITIVE)
    if ask < bid:
        return CtpQuoteValidation(None, CtpCohortReason.QUOTE_CROSSED)
    if lower_limit <= 0.0 or upper_limit <= lower_limit:
        return CtpQuoteValidation(None, CtpCohortReason.DAILY_PRICE_LIMIT_INVALID)
    if any(price < lower_limit or price > upper_limit for price in (bid, ask, last)):
        return CtpQuoteValidation(None, CtpCohortReason.QUOTE_OUTSIDE_DAILY_LIMIT)
    if any(
        not _on_tick_grid(price, leg.price_tick)
        for price in (bid, ask, last, lower_limit, upper_limit)
    ):
        return CtpQuoteValidation(None, CtpCohortReason.QUOTE_OFF_TICK_GRID)
    if source_clock_error_ms < 0.0 or source_clock_error_ms > policy.max_source_clock_error_ms:
        return CtpQuoteValidation(None, CtpCohortReason.SOURCE_CLOCK_ERROR_INVALID)
    if receive_clock_error_ms < 0.0 or receive_clock_error_ms > policy.max_receive_clock_error_ms:
        return CtpQuoteValidation(None, CtpCohortReason.RECEIVE_CLOCK_ERROR_INVALID)

    source_epoch = _epoch_seconds(_event_value(event, "event_time_utc", "timestamp"))
    if source_epoch is None:
        return CtpQuoteValidation(None, CtpCohortReason.SOURCE_TIME_INVALID)
    receive_epoch = _epoch_seconds(
        _event_value(event, "recv_time_utc", "received_wall_time", "local_time")
    )
    if receive_epoch is None:
        return CtpQuoteValidation(None, CtpCohortReason.RECEIVE_TIME_INVALID)
    receive_monotonic_ns = _strict_positive_uint64(
        _event_value(event, "recv_monotonic_ns", "received_monotonic_ns")
    )
    ingest_seq = _strict_positive_uint64(_event_value(event, "ingest_seq", "sequence"))
    connection_generation = _strict_positive_uint64(_event_value(event, "connection_generation"))
    subscription_epoch = _strict_positive_uint64(_event_value(event, "subscription_epoch"))
    if None in (receive_monotonic_ns, ingest_seq, connection_generation, subscription_epoch):
        return CtpQuoteValidation(None, CtpCohortReason.QUOTE_IDENTITY_TYPE_INVALID)
    trading_day = _event_value(event, "trading_day", "TradingDay")
    if not _valid_trading_day(trading_day):
        return CtpQuoteValidation(None, CtpCohortReason.TRADING_DAY_INVALID)
    action_day = _event_value(event, "action_day", "ActionDay")
    if not _valid_trading_day(action_day):
        return CtpQuoteValidation(None, CtpCohortReason.ACTION_DAY_INVALID)
    clock_domain_id = _event_value(event, "clock_domain_id")
    if not _is_provenance_identity(clock_domain_id):
        return CtpQuoteValidation(None, CtpCohortReason.CLOCK_DOMAIN_UNKNOWN)
    if source_epoch > receive_epoch:
        return CtpQuoteValidation(None, CtpCohortReason.SOURCE_TIME_AFTER_RECEIVE)

    return CtpQuoteValidation(
        CtpQuoteEvidence(
            symbol=symbol,
            exchange=exchange,
            asset_type=asset_type if isinstance(asset_type, str) else None,
            bid=bid,
            ask=ask,
            bid_size=bid_size,
            ask_size=ask_size,
            last=last,
            lower_limit=lower_limit,
            upper_limit=upper_limit,
            source_epoch=source_epoch,
            receive_epoch=receive_epoch,
            receive_monotonic_ns=receive_monotonic_ns,
            ingest_seq=ingest_seq,
            connection_generation=connection_generation,
            subscription_epoch=subscription_epoch,
            trading_day=trading_day,
            action_day=action_day,
            clock_domain_id=clock_domain_id,
            rules_hash=rules_hash,
            source=source,
            event_time_source=event_time_source,
            source_clock_error_ms=source_clock_error_ms,
            receive_clock_error_ms=receive_clock_error_ms,
        ),
        None,
    )


class CtpQuoteCohortValidator:
    """Statefully admit only fresh, synchronized CTP quote cohorts.

    ``expected_legs`` is copied to an immutable tuple at construction.  Each
    call to :meth:`ingest` either returns a reason or one immutable cohort.
    The caller supplies :class:`CtpCohortNow` evidence on every call; this
    avoids treating an arrival as the current time and makes queue delays
    fail closed.  Sequence and admission watermarks are partitioned by
    ``(connection_generation, subscription_epoch)`` so a verified reconnect
    can restart its ingest sequence at one without mixing generations.
    """

    def __init__(
        self,
        *,
        expected_legs: Iterable[CtpCohortLeg],
        expected_rules_hash: str,
        policy: CtpCohortPolicy,
    ) -> None:
        legs = tuple(expected_legs)
        if len(legs) not in (2, 3):
            raise ValueError("expected_legs must contain exactly two or three CtpCohortLeg values")
        if not all(isinstance(leg, CtpCohortLeg) for leg in legs):
            raise TypeError("expected_legs must contain only CtpCohortLeg values")
        symbols = tuple(leg.symbol for leg in legs)
        if len(set(symbols)) != len(symbols):
            raise ValueError("expected_legs must have unique symbols")
        exchanges = {leg.exchange for leg in legs}
        if len(exchanges) != 1:
            raise ValueError("expected_legs must use one exchange")
        if not isinstance(policy, CtpCohortPolicy):
            raise TypeError("policy must be a CtpCohortPolicy")

        self.expected_legs = legs
        self.expected_rules_hash = _strict_provenance_identity(
            expected_rules_hash,
            field="expected_rules_hash",
        )
        self.policy = policy
        self._legs_by_symbol = MappingProxyType({leg.symbol: leg for leg in legs})
        self._latest: dict[str, CtpQuoteEvidence] = {}
        self._active_scope: Optional[Tuple[int, int]] = None
        # Both values are producer-owned unsigned incarnations.  Lexicographic
        # order permits a new connection to restart its subscription epoch,
        # while a delayed packet from any previously observed incarnation can
        # never make the validator move backwards.
        self._highest_scope: Optional[Tuple[int, int]] = None
        self._retired_scopes: set[Tuple[int, int]] = set()
        self._last_seen_by_scope: dict[Tuple[int, int], dict[str, CtpQuoteEvidence]] = {}
        self._last_admitted_sequences: dict[Tuple[int, int], dict[str, int]] = {}
        self._confirmed_cohort: Optional[CtpQuoteCohort] = None

    @property
    def expected_symbols(self) -> Tuple[str, ...]:
        """Configured symbols in their caller-supplied, frozen order."""

        return tuple(leg.symbol for leg in self.expected_legs)

    def reset(self) -> None:
        """Discard retained evidence, for example after an explicit session reset."""

        self._latest.clear()
        self._active_scope = None
        self._highest_scope = None
        self._retired_scopes.clear()
        self._last_seen_by_scope.clear()
        self._last_admitted_sequences.clear()
        self._confirmed_cohort = None

    def ingest(self, event: Any, *, now: Any = None) -> CtpCohortResult:
        """Validate one quote and return a cohort only when all legs are fresh."""

        symbol = _event_value(event, "symbol", "instrument_id", "InstrumentID")
        if not isinstance(symbol, str) or not symbol:
            return CtpCohortResult(None, CtpCohortReason.QUOTE_SYMBOL_MISSING)
        leg = self._legs_by_symbol.get(symbol)
        if leg is None:
            return CtpCohortResult(None, CtpCohortReason.UNEXPECTED_SYMBOL)
        raw_scope = _scope_from_event(event)
        if self._is_scope_rollback(raw_scope):
            # A delayed prior connection/subscription packet is neither a
            # signal nor a reason to invalidate the current newer round.
            return CtpCohortResult(None, CtpCohortReason.RETIRED_CONNECTION_SCOPE)
        validation = validate_ctp_quote(
            event,
            leg=leg,
            expected_rules_hash=self.expected_rules_hash,
            policy=self.policy,
        )
        if validation.quote is None:
            self._invalidate_after_expected_failure(_scope_from_event(event))
            return CtpCohortResult(None, validation.reason)
        quote = validation.quote
        scope = (quote.connection_generation, quote.subscription_epoch)
        if self._is_scope_rollback(scope) or scope in self._retired_scopes:
            return CtpCohortResult(None, CtpCohortReason.RETIRED_CONNECTION_SCOPE)
        if self._highest_scope is None or scope > self._highest_scope:
            self._highest_scope = scope
        if self._active_scope != scope:
            self._activate_scope(scope)
        trusted_now, now_reason = _normalize_trusted_now(now, policy=self.policy)
        if trusted_now is None:
            self._invalidate_current_round()
            return CtpCohortResult(None, now_reason)
        quote_time_reason = self._validate_quote_at(quote, now=trusted_now)
        if quote_time_reason is not None:
            self._invalidate_current_round()
            return CtpCohortResult(None, quote_time_reason)

        prior = self._last_seen_by_scope.get(scope, {}).get(quote.symbol)
        if prior is not None:
            if quote.ingest_seq <= prior.ingest_seq:
                self._invalidate_current_round()
                return CtpCohortResult(None, CtpCohortReason.DUPLICATE_OR_OUT_OF_ORDER)
            if quote.receive_monotonic_ns < prior.receive_monotonic_ns:
                self._invalidate_current_round()
                return CtpCohortResult(None, CtpCohortReason.OUT_OF_ORDER_RECEIVE_TIME)
            if quote.source_epoch < prior.source_epoch:
                self._invalidate_current_round()
                return CtpCohortResult(None, CtpCohortReason.OUT_OF_ORDER_SOURCE_TIME)

        if self._confirmed_cohort is not None:
            confirmed_quote = self._confirmed_cohort.quote_for(quote.symbol)
            if quote.update_identity != confirmed_quote.update_identity:
                # A newer valid update makes the prior all-leg decision stale
                # even before the remaining legs complete their next round.
                self._confirmed_cohort = None
        self._last_seen_by_scope.setdefault(scope, {})[quote.symbol] = quote
        self._latest[quote.symbol] = quote
        if len(self._latest) != len(self.expected_legs):
            return CtpCohortResult(None, CtpCohortReason.WAITING_FOR_LEGS)

        quotes = {symbol: self._latest[symbol] for symbol in self.expected_symbols}
        cohort_reason = self._validate_cohort(quotes, now=trusted_now)
        if cohort_reason is not None:
            self._invalidate_current_round()
            return CtpCohortResult(None, cohort_reason)
        admission_watermark = self._last_admitted_sequences.setdefault(
            scope,
            dict.fromkeys(self.expected_symbols, 0),
        )
        if any(
            quotes[symbol].ingest_seq <= admission_watermark[symbol]
            for symbol in self.expected_symbols
        ):
            return CtpCohortResult(None, CtpCohortReason.WAITING_FOR_ALL_LEGS_NEW)

        self._last_admitted_sequences[scope] = {
            symbol: quotes[symbol].ingest_seq for symbol in self.expected_symbols
        }
        first = quotes[self.expected_symbols[0]]
        cohort = self._make_cohort(quotes, first=first)
        self._confirmed_cohort = cohort
        return CtpCohortResult(cohort, None)

    def validate_at(self, *, now: Any = None) -> CtpCohortResult:
        """Recheck the currently confirmed cohort immediately before use.

        A caller should invoke this at the final execution boundary.  The
        method does not create an order; it only proves that the previously
        admitted immutable evidence is still fresh against caller-supplied,
        trusted time evidence.
        """

        cohort = self._confirmed_cohort
        if cohort is None:
            return CtpCohortResult(None, CtpCohortReason.NO_CONFIRMED_COHORT)
        trusted_now, now_reason = _normalize_trusted_now(now, policy=self.policy)
        if trusted_now is None:
            self._invalidate_current_round()
            return CtpCohortResult(None, now_reason)
        scope = (cohort.connection_generation, cohort.subscription_epoch)
        if self._active_scope != scope or scope in self._retired_scopes:
            self._invalidate_current_round()
            return CtpCohortResult(None, CtpCohortReason.RETIRED_CONNECTION_SCOPE)
        cohort_reason = self._validate_cohort(cohort.quotes, now=trusted_now)
        if cohort_reason is not None:
            self._invalidate_current_round()
            return CtpCohortResult(None, cohort_reason)
        return CtpCohortResult(cohort, None)

    def recheck(self, *, now: Any = None) -> CtpCohortResult:
        """Alias for :meth:`validate_at` at an execution submission boundary."""

        return self.validate_at(now=now)

    def _invalidate_current_round(self) -> None:
        """Forget retained quote and confirmation evidence after a failed gate.

        Sequence watermarks remain scoped and retained.  Therefore recovery
        requires a fresh valid quote from every leg and cannot reuse a prior
        admitted update identity.
        """

        self._latest.clear()
        self._confirmed_cohort = None

    def _invalidate_after_expected_failure(self, failed_scope: Optional[Tuple[int, int]]) -> None:
        """Invalidate evidence and retire an older scope when raw identity proves a switch."""

        if self._is_scope_rollback(failed_scope):
            return
        if (
            failed_scope is not None
            and failed_scope not in self._retired_scopes
            and self._active_scope != failed_scope
        ):
            if self._highest_scope is None or failed_scope > self._highest_scope:
                self._highest_scope = failed_scope
            self._activate_scope(failed_scope)
            return
        self._invalidate_current_round()

    def _is_scope_rollback(self, scope: Optional[Tuple[int, int]]) -> bool:
        """Return true when a raw quote is from an older producer incarnation."""

        return scope is not None and self._highest_scope is not None and scope < self._highest_scope

    def _activate_scope(self, scope: Tuple[int, int]) -> None:
        """Start a new connection/subscription scope without mixing evidence."""

        if self._active_scope == scope:
            return
        if self._active_scope is not None:
            self._retired_scopes.add(self._active_scope)
        self._invalidate_current_round()
        self._active_scope = scope

    def _validate_quote_at(
        self,
        quote: CtpQuoteEvidence,
        *,
        now: CtpCohortNow,
    ) -> Optional[str]:
        """Validate absolute freshness against trusted same-domain current time."""

        if quote.clock_domain_id != now.clock_domain_id:
            return CtpCohortReason.NOW_CLOCK_DOMAIN_MISMATCH
        if now.now_monotonic_ns < quote.receive_monotonic_ns:
            return CtpCohortReason.OUT_OF_ORDER_RECEIVE_TIME
        monotonic_age_ms = (now.now_monotonic_ns - quote.receive_monotonic_ns) / 1_000_000.0
        if monotonic_age_ms > self.policy.max_receive_age_ms:
            return CtpCohortReason.STALE_COHORT_RECEIVE_TIME

        now_wall_high = now.now_epoch + now.receive_clock_error_ms / 1_000.0
        quote_receive_low = quote.receive_epoch - quote.receive_clock_error_ms / 1_000.0
        quote_source_low = quote.source_epoch - quote.source_clock_error_ms / 1_000.0
        if now_wall_high < quote_receive_low or now_wall_high < quote_source_low:
            return CtpCohortReason.NOW_WALL_TIME_BEFORE_QUOTE
        receive_age_ms = (now_wall_high - quote_receive_low) * 1_000.0
        if receive_age_ms > self.policy.max_receive_age_ms:
            return CtpCohortReason.STALE_COHORT_RECEIVE_TIME
        source_age_ms = (now_wall_high - quote_source_low) * 1_000.0
        if source_age_ms > self.policy.max_source_age_ms:
            return CtpCohortReason.STALE_COHORT_SOURCE_TIME
        return None

    def _make_cohort(
        self,
        quotes: Mapping[str, CtpQuoteEvidence],
        *,
        first: CtpQuoteEvidence,
    ) -> CtpQuoteCohort:
        cohort_id = "|".join(
            f"{symbol}:{quotes[symbol].connection_generation}:{quotes[symbol].subscription_epoch}:"
            f"{quotes[symbol].ingest_seq}"
            for symbol in sorted(quotes)
        )
        return CtpQuoteCohort(
            quotes=MappingProxyType(dict(quotes)),
            exchange=first.exchange,
            trading_day=first.trading_day,
            action_day=first.action_day,
            connection_generation=first.connection_generation,
            subscription_epoch=first.subscription_epoch,
            clock_domain_id=first.clock_domain_id,
            rules_hash=first.rules_hash,
            cohort_id=cohort_id,
        )

    def _validate_cohort(
        self,
        quotes: Mapping[str, CtpQuoteEvidence],
        *,
        now: CtpCohortNow,
    ) -> Optional[str]:
        if tuple(quotes) != self.expected_symbols:
            return CtpCohortReason.WAITING_FOR_LEGS
        if any(quotes[symbol].symbol != symbol for symbol in self.expected_symbols):
            return CtpCohortReason.WAITING_FOR_LEGS
        if len({quote.exchange for quote in quotes.values()}) != 1:
            return CtpCohortReason.COHORT_EXCHANGE_MISMATCH
        if len({quote.trading_day for quote in quotes.values()}) != 1:
            return CtpCohortReason.COHORT_TRADING_DAY_MISMATCH
        if len({quote.action_day for quote in quotes.values()}) != 1:
            return CtpCohortReason.COHORT_ACTION_DAY_MISMATCH
        if len({quote.connection_generation for quote in quotes.values()}) != 1:
            return CtpCohortReason.COHORT_CONNECTION_GENERATION_MISMATCH
        if len({quote.subscription_epoch for quote in quotes.values()}) != 1:
            return CtpCohortReason.COHORT_SUBSCRIPTION_EPOCH_MISMATCH
        if len({quote.rules_hash for quote in quotes.values()}) != 1:
            return CtpCohortReason.COHORT_RULES_HASH_MISMATCH
        if len({quote.clock_domain_id for quote in quotes.values()}) != 1:
            return CtpCohortReason.COHORT_CLOCK_DOMAIN_MISMATCH

        for quote in quotes.values():
            quote_time_reason = self._validate_quote_at(quote, now=now)
            if quote_time_reason is not None:
                return quote_time_reason

        receive_values = [quote.receive_monotonic_ns for quote in quotes.values()]
        receive_skew_ms = (max(receive_values) - min(receive_values)) / 1_000_000.0
        if receive_skew_ms > self.policy.max_receive_skew_ms:
            return CtpCohortReason.BLOCKED_CROSS_LEG_SKEW

        source_lows = [
            quote.source_epoch - quote.source_clock_error_ms / 1_000.0 for quote in quotes.values()
        ]
        source_highs = [
            quote.source_epoch + quote.source_clock_error_ms / 1_000.0 for quote in quotes.values()
        ]
        source_skew_ms = (max(source_highs) - min(source_lows)) * 1_000.0
        if source_skew_ms > self.policy.max_source_skew_ms:
            return CtpCohortReason.BLOCKED_SOURCE_SKEW
        return None


__all__ = [
    "CtpCohortPolicy",
    "CtpCohortNow",
    "CtpCohortReason",
    "CtpCohortLeg",
    "CtpQuoteEvidence",
    "CtpQuoteValidation",
    "CtpQuoteCohort",
    "CtpCohortResult",
    "CtpQuoteCohortValidator",
    "validate_ctp_quote",
]
