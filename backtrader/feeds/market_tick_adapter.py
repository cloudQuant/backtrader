"""Backtrader projection for authenticated, provider-neutral SDK tick events."""

from __future__ import annotations

from types import SimpleNamespace


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

    (
        _MarketClockQuality,
        MarketFreshnessStatus,
        _MarketTickEvent,
        schema,
        version,
    ) = _load_market_tick_types()
    try:
        from bt_api_py.market_tick_contracts import (
            MarketTickQualificationError,
            require_qualified_market_tick,
        )
    except (ImportError, AttributeError) as exc:
        raise MarketTickAdapterError("MARKET_TICK_API_UNAVAILABLE") from exc
    try:
        value, event_time, received_at = require_qualified_market_tick(value)
    except MarketTickQualificationError as exc:
        raise MarketTickAdapterError(exc.code, market_tick_event=value) from exc

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
        data_clock_qualified=True,
        quality_flags=list(data.quality_flags),
    )
    return fields


__all__ = [
    "MarketTickAdapterError",
    "adapt_market_tick_event",
    "is_market_tick_event_candidate",
]
