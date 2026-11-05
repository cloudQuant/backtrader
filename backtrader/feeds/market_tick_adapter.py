"""Backtrader projection for authenticated, provider-neutral SDK tick events.

Two entry points share one field projection:

* :func:`adapt_market_tick_event` (strict) rejects any tick whose clocks and
  freshness the SDK has not qualified.
* :func:`ingest_market_tick_event` (iteration 62, D62-27) admits every tick
  that carries a parseable provider event time and local receive time, and
  returns a separate :class:`MarketTickQualification` saying whether the tick
  could back a live order at receipt. Missing or unparseable times are an
  ingestion error code, never a substituted time.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime, timezone
from types import SimpleNamespace
from typing import Optional, Tuple


class MarketTickAdapterError(ValueError):
    """Finite, value-free failure while adapting an SDK market tick."""

    _CODES = frozenset(
        {
            "TICK_CLOCK_UNAVAILABLE",
            "MARKET_DATA_FRESHNESS_UNAVAILABLE",
            "MARKET_DATA_STALE",
            "MARKET_TICK_API_UNAVAILABLE",
            "MARKET_TICK_EVENT_INVALID",
        }
    )

    def __init__(self, code, *, market_tick_event=None):
        self.code = code if type(code) is str and code in self._CODES else "MARKET_TICK_EVENT_INVALID"
        self.market_tick_event = market_tick_event
        super().__init__(self.code)


_RESOLVED = []  # [(types tuple, require_qualified, qualification error)] once imported


def _resolved_market_tick_api():
    """The SDK names used per tick, imported once (an import is a lookup per call)."""
    if _RESOLVED:
        return _RESOLVED[0]
    types = _load_market_tick_types()
    try:
        from bt_api_py.market_tick_contracts import (
            MarketTickQualificationError,
            require_qualified_market_tick,
        )
    except (ImportError, AttributeError) as exc:
        raise MarketTickAdapterError("MARKET_TICK_API_UNAVAILABLE") from exc
    resolved = (types, require_qualified_market_tick, MarketTickQualificationError)
    _RESOLVED.append(resolved)
    return resolved


def _load_market_tick_types():
    try:
        from bt_api_py.market_tick_contracts import (
            MarketClockQuality,
            MarketFreshnessStatus,
            MarketTickEvent,
            MARKET_TICK_SCHEMA,
            MARKET_TICK_SCHEMA_VERSION,
        )
    except (ImportError, AttributeError) as exc:
        raise MarketTickAdapterError("MARKET_TICK_API_UNAVAILABLE") from exc
    return (
        MarketClockQuality,
        MarketFreshnessStatus,
        MarketTickEvent,
        MARKET_TICK_SCHEMA,
        MARKET_TICK_SCHEMA_VERSION,
    )


def is_market_tick_event_candidate(value):
    """Return whether the object has the exact public SDK tick type."""

    try:
        _, _, market_tick_event, _, _ = _load_market_tick_types()
    except MarketTickAdapterError:
        return False
    return type(value) is market_tick_event


def adapt_market_tick_event(value):
    """Adapt one exact SDK tick event; reject unqualified data clocks.

    The poll result must be the exact public SDK type. A provider-reported
    event timestamp or a poll-return observation cannot qualify a Backtrader
    tick. The SDK must verify both clocks and freshness before this projection
    can be used for lines or strategy dispatch.
    """

    types, require_qualified_market_tick, MarketTickQualificationError = (
        _resolved_market_tick_api()
    )
    try:
        value, event_time, received_at = require_qualified_market_tick(value)
    except MarketTickQualificationError as exc:
        raise MarketTickAdapterError(exc.code, market_tick_event=value) from exc
    return _project_market_tick(value, event_time, received_at, types, data_clock_qualified=True)


def _project_market_tick(value, event_time, received_at, types, *, data_clock_qualified):
    """Project one exact SDK tick event onto Backtrader tick fields."""

    (
        _MarketClockQuality,
        MarketFreshnessStatus,
        _MarketTickEvent,
        schema,
        version,
    ) = types
    clock = value.clock
    data = value.data
    instrument = value.key.instrument
    fields = SimpleNamespace(
        sdk_market_tick=True,
        market_tick_event=value,
        schema_version="%s.v%d" % (schema, version),
        schema=schema,
        schema_version_number=version,
        symbol=instrument.instrument_id,
        instrument_id=instrument.instrument_id,
        exchange=instrument.venue,
        venue=instrument.venue,
        asset_type=instrument.product_type,
        provider=instrument.provider,
        price=data.last_price,
        last_price=data.last_price,
        bid_price=data.bid_price,
        ask_price=data.ask_price,
        bid_volume=data.bid_size,
        ask_volume=data.ask_size,
        lower_limit_price=data.lower_limit,
        upper_limit_price=data.upper_limit,
        turnover=data.turnover,
        open_interest=data.open_interest,
        volume=data.delta_volume,
        delta_volume=data.delta_volume,
        cum_volume=data.cumulative_volume,
        cumulative_volume=data.cumulative_volume,
        volume_semantics="delta" if data.delta_volume is not None else "unknown",
        volume_complete=data.volume_complete,
        volume_quality=data.volume_quality,
        continuity_status=data.continuity_status,
        trading_date=data.trading_date,
        event_session_date=data.event_session_date,
        trading_day=data.trading_date,
        action_day=data.event_session_date,
        provider_event_time_utc=clock.provider_event_time_utc,
        event_time_provenance=data.event_time_provenance,
        event_time_utc=event_time,
        timestamp=event_time.timestamp(),
        datetime=event_time,
        received_at_utc=clock.received_at_utc,
        recv_time_utc=received_at,
        received_wall_time=received_at.timestamp(),
        recv_monotonic_ns=clock.received_monotonic_ns,
        received_monotonic_ns=clock.received_monotonic_ns,
        source=data.provider_source,
        provider_source=data.provider_source,
        quality_contract_ref=data.quality_contract_ref,
        rules_hash=data.quality_contract_ref,
        connection_generation=value.source.connection_generation,
        ingest_seq=data.provider_sequence,
        provider_sequence=data.provider_sequence,
        provider_subscription_epoch=data.provider_subscription_epoch,
        subscription_epoch=data.provider_subscription_epoch,
        sequence=value.cursor.sequence,
        cursor_sequence=value.cursor.sequence,
        stream_id=value.cursor.stream_id,
        stream_epoch=value.cursor.epoch,
        clock_domain_id=value.source.clock_domain_id,
        clock_source_session_id=value.source.clock_source_session_id,
        clock_source=value.source.clock_source,
        source_clock_quality=clock.source_clock_quality.value,
        receive_clock_quality=clock.receive_clock_quality.value,
        source_clock_error_ms=clock.source_clock_error_ms,
        receive_clock_error_ms=clock.receive_clock_error_ms,
        freshness_status=clock.freshness_status.value,
        freshness_reason_codes=clock.freshness_reason_codes,
        freshness_verified=clock.freshness_status is MarketFreshnessStatus.FRESH,
        stale=clock.freshness_status is MarketFreshnessStatus.STALE,
        stale_reason="" if clock.freshness_status is MarketFreshnessStatus.FRESH else None,
        execution_eligible=data.execution_eligible,
        bar_eligible=bool(data.volume_complete and data.delta_volume is not None),
        quality="GOOD" if not data.quality_flags else "INVALID",
        data_clock_qualified=data_clock_qualified,
        quality_flags=list(data.quality_flags),
    )
    return fields


# Finite ingestion error codes: the tick cannot enter data lines because a
# required time is missing or unparseable (D62-27). No time is substituted.
MARKET_TICK_INGEST_ERROR_CODES = frozenset(
    {
        "TICK_EVENT_TIME_UNAVAILABLE",
        "TICK_RECEIVE_TIME_UNAVAILABLE",
        "TICK_RECEIVE_MONOTONIC_UNAVAILABLE",
    }
)

# Finite reasons why an admitted tick is not trade-qualified at receipt.
MARKET_TICK_QUALIFICATION_REASONS = frozenset(
    {
        "SOURCE_CLOCK_UNVERIFIED",
        "RECEIVE_CLOCK_UNVERIFIED",
        "FRESHNESS_UNAVAILABLE",
        "FRESHNESS_STALE",
        "FRESHNESS_INVALID",
        "UPSTREAM_EXECUTION_INELIGIBLE",
        "EVENT_TIME_AFTER_RECEIVE",
        "EVENT_TIME_MAX_AGE_INVALID",
        "EVENT_TIME_STALE",
    }
)


@dataclass(frozen=True)
class MarketTickQualification:
    """Whether one admitted SDK tick could back a live order when received.

    ``trade_qualified_at_receipt`` holds only when the SDK reports both the
    source and the receive clock VERIFIED, freshness FRESH and the tick
    execution eligible, the event time is not after the receive time, and the
    measured event-to-receive latency is at most ``event_time_max_age``
    (compared directly, D62-37). It is a receipt-time fact: the age since
    ``received_monotonic_ns`` must still be re-checked when an order is made
    (D62-21). Neither field asserts that a clock is calibrated.
    """

    trade_qualified_at_receipt: bool
    qualification_reasons: Tuple[str, ...]
    event_time_utc: datetime
    received_at_utc: datetime
    received_monotonic_ns: int
    event_to_receive_seconds: float


@dataclass(frozen=True)
class MarketTickIngestResult:
    """Outcome of :func:`ingest_market_tick_event` / :func:`qualify_market_tick_event`.

    Exactly one of ``qualification`` and ``error_code`` is set. ``tick`` is
    the projected Backtrader tick (``None`` for an ingestion error and for
    :func:`qualify_market_tick_event`).
    """

    tick: Optional[SimpleNamespace]
    qualification: Optional[MarketTickQualification]
    error_code: Optional[str]


def _aware_utc(text):
    """Parse one SDK UTC text; ``None`` when absent, unparseable or naive."""
    if type(text) is not str or not text:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        return None
    return parsed.astimezone(timezone.utc)


def _max_age_seconds(value):
    """A finite, non-negative age limit in seconds, otherwise ``None``."""
    if type(value) is bool:
        return None
    try:
        limit = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    if not math.isfinite(limit) or limit < 0:
        return None
    return limit


def _qualify(value, types, event_time_max_age):
    """Return ``(qualification, error_code, event_time, received_at)``."""
    MarketClockQuality, MarketFreshnessStatus, MarketTickEvent, _schema, _version = types
    if type(value) is not MarketTickEvent:
        raise MarketTickAdapterError("MARKET_TICK_EVENT_INVALID", market_tick_event=value)
    clock = value.clock
    event_time = _aware_utc(clock.provider_event_time_utc)
    if event_time is None:
        return None, "TICK_EVENT_TIME_UNAVAILABLE", None, None
    received_at = _aware_utc(clock.received_at_utc)
    if received_at is None:
        return None, "TICK_RECEIVE_TIME_UNAVAILABLE", None, None
    received_monotonic_ns = clock.received_monotonic_ns
    if type(received_monotonic_ns) is not int or received_monotonic_ns <= 0:
        return None, "TICK_RECEIVE_MONOTONIC_UNAVAILABLE", None, None

    reasons = []
    if clock.source_clock_quality is not MarketClockQuality.VERIFIED:
        reasons.append("SOURCE_CLOCK_UNVERIFIED")
    if clock.receive_clock_quality is not MarketClockQuality.VERIFIED:
        reasons.append("RECEIVE_CLOCK_UNVERIFIED")
    status = clock.freshness_status
    if status is MarketFreshnessStatus.UNAVAILABLE:
        reasons.append("FRESHNESS_UNAVAILABLE")
    elif status is MarketFreshnessStatus.STALE:
        reasons.append("FRESHNESS_STALE")
    elif status is not MarketFreshnessStatus.FRESH:
        reasons.append("FRESHNESS_INVALID")
    if value.data.execution_eligible is not True:
        # The SDK's own verdict; Backtrader never promotes it (fail closed).
        reasons.append("UPSTREAM_EXECUTION_INELIGIBLE")
    latency = (received_at - event_time).total_seconds()
    limit = _max_age_seconds(event_time_max_age)
    if latency < 0:
        reasons.append("EVENT_TIME_AFTER_RECEIVE")
    elif limit is None:
        reasons.append("EVENT_TIME_MAX_AGE_INVALID")
    elif latency > limit:
        reasons.append("EVENT_TIME_STALE")
    qualification = MarketTickQualification(
        trade_qualified_at_receipt=not reasons,
        qualification_reasons=tuple(reasons),
        event_time_utc=event_time,
        received_at_utc=received_at,
        received_monotonic_ns=received_monotonic_ns,
        event_to_receive_seconds=latency,
    )
    return qualification, None, event_time, received_at


def qualify_market_tick_event(value, *, event_time_max_age):
    """Classify one exact SDK tick's receipt-time trade qualification only.

    Never raises for a missing or unparseable time (that is ``error_code``);
    raises :class:`MarketTickAdapterError` only when the SDK API is missing or
    ``value`` is not the exact public SDK tick type.
    """

    types = _resolved_market_tick_api()[0]
    qualification, error_code, _event_time, _received_at = _qualify(
        value, types, event_time_max_age
    )
    return MarketTickIngestResult(tick=None, qualification=qualification, error_code=error_code)


def ingest_market_tick_event(value, *, event_time_max_age):
    """Project one exact SDK tick for data lines, with its trade qualification.

    Unlike :func:`adapt_market_tick_event`, an unverified clock, unavailable or
    stale freshness, or a large event-to-receive latency does not reject the
    tick: it is projected for bars and indicators and marked not
    trade-qualified. A missing or unparseable provider event time, receive
    time or receive monotonic time is returned as ``error_code`` (one of
    :data:`MARKET_TICK_INGEST_ERROR_CODES`) without a projection. Raises
    :class:`MarketTickAdapterError` only when the SDK API is missing or
    ``value`` is not the exact public SDK tick type.
    """

    types = _resolved_market_tick_api()[0]
    qualification, error_code, event_time, received_at = _qualify(
        value, types, event_time_max_age
    )
    if error_code is not None:
        return MarketTickIngestResult(tick=None, qualification=None, error_code=error_code)
    fields = _project_market_tick(
        value, event_time, received_at, types, data_clock_qualified=value.data_clock_qualified
    )
    fields.trade_qualified_at_receipt = qualification.trade_qualified_at_receipt
    fields.qualification_reasons = qualification.qualification_reasons
    return MarketTickIngestResult(tick=fields, qualification=qualification, error_code=None)


__all__ = [
    "MARKET_TICK_INGEST_ERROR_CODES",
    "MARKET_TICK_QUALIFICATION_REASONS",
    "MarketTickAdapterError",
    "MarketTickIngestResult",
    "MarketTickQualification",
    "adapt_market_tick_event",
    "ingest_market_tick_event",
    "is_market_tick_event_candidate",
    "qualify_market_tick_event",
]
