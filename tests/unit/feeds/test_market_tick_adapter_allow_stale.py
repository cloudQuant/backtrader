"""Receipt-time qualification of the ``allow_stale_event_time`` opt-in.

Default remains strict: a stale event time still fails the qualification.
With the explicit opt-in only the event-stale reasons (and an upstream
ineligibility that only echoes them) are exempted; every other defect --
unverified clocks, unavailable freshness, an event time after its receive
time -- keeps the tick non-tradable.
"""

from __future__ import annotations

import pytest

market_tick_protocol = pytest.importorskip("bt_api_base.market_tick_protocol")
market_protocol = pytest.importorskip("bt_api_base.market_protocol")

from backtrader.feeds.market_tick_adapter import (  # noqa: E402
    MarketTickAdapterError,
    ingest_market_tick_event,
    qualify_market_tick_event,
)

MarketClockQuality = market_tick_protocol.MarketClockQuality
MarketFreshnessStatus = market_tick_protocol.MarketFreshnessStatus
MarketEventCursor = market_tick_protocol.MarketEventCursor
MarketTickPayload = market_tick_protocol.MarketTickPayload
bind_market_tick_event = market_tick_protocol.bind_market_tick_event

INSTRUMENT = market_protocol.MarketInstrumentKey(
    provider="ctp",
    venue="CZCE",
    environment="simulation",
    product_type="future",
    instrument_id="SA609",
    native_symbol="SA609",
)
SUBSCRIPTION = market_protocol.MarketSubscriptionKey(
    source_ref="ctp.md.front",
    entitlement_ref="test-entitlement",
    instrument=INSTRUMENT,
    channel="tick",
)
SOURCE = market_protocol.MarketSourceDescriptor(
    key=SUBSCRIPTION,
    stream_id=SUBSCRIPTION.stream_id,
    epoch="epoch-1",
    provider="ctp",
    source="ctp.native.md",
    connection_generation=1,
    clock_domain_id="clock-domain-1",
    clock_source_session_id="clock-session-1",
    clock_source="ctp.exchange",
)


def _payload(**overrides):
    values = dict(
        instrument=INSTRUMENT,
        last_price=1500.0,
        bid_price=1499.0,
        ask_price=1501.0,
        bid_size=10.0,
        ask_size=12.0,
        lower_limit=1400.0,
        upper_limit=1600.0,
        turnover=1.0e8,
        open_interest=5000.0,
        delta_volume=3.0,
        cumulative_volume=12345.0,
        volume_complete=True,
        volume_quality="CONTINUOUS",
        continuity_status="continuous",
        trading_date="2026-11-02",
        event_session_date="2026-11-02",
        provider_event_time_utc="2026-11-02T01:59:57.500000Z",
        event_time_provenance="provider_reported",
        received_at_utc="2026-11-02T02:00:00.600000Z",
        received_monotonic_ns=123456789,
        provider_source="ctp.native.md",
        quality_contract_ref="ctp.quote.v2:allow_stale=1",
        provider_connection_generation=1,
        provider_sequence=7,
        provider_subscription_epoch=1,
        clock_domain_id="clock-domain-1",
        clock_source_session_id="clock-session-1",
        clock_source="ctp.exchange",
        source_clock_quality=MarketClockQuality.VERIFIED,
        receive_clock_quality=MarketClockQuality.VERIFIED,
        source_clock_error_ms=1.0,
        receive_clock_error_ms=1.0,
        freshness_status=MarketFreshnessStatus.STALE,
        freshness_reason_codes=("EVENT_TIME_STALE",),
        execution_eligible=True,
        quality_flags=(),
    )
    values.update(overrides)
    return MarketTickPayload(**values)


def _event(**overrides):
    return bind_market_tick_event(
        _payload(**overrides),
        SOURCE,
        MarketEventCursor(stream_id=SOURCE.stream_id, epoch=SOURCE.epoch, sequence=7),
    )


def test_default_stays_strict_for_every_stale_shape():
    qualification = qualify_market_tick_event(
        _event(execution_eligible=False), event_time_max_age=2.0
    ).qualification
    assert qualification.trade_qualified_at_receipt is False
    assert "FRESHNESS_STALE" in qualification.qualification_reasons
    assert "EVENT_TIME_STALE" in qualification.qualification_reasons
    assert "UPSTREAM_EXECUTION_INELIGIBLE" in qualification.qualification_reasons


def test_opt_in_exempts_only_the_stale_event_reasons():
    result = ingest_market_tick_event(
        _event(), event_time_max_age=2.0, allow_stale_event_time=True
    )
    assert result.error_code is None
    assert result.qualification.trade_qualified_at_receipt is True
    assert result.qualification.qualification_reasons == ()
    assert result.tick is not None  # still projected for data lines


def test_opt_in_keeps_unverified_clocks_closed():
    qualification = qualify_market_tick_event(
        _event(
            source_clock_quality=MarketClockQuality.UNKNOWN,
            source_clock_error_ms=None,
            execution_eligible=False,
            freshness_status=MarketFreshnessStatus.UNAVAILABLE,
            freshness_reason_codes=("SOURCE_CLOCK_CALIBRATION_NOT_PROVIDED",),
            quality_contract_ref=None,
        ),
        event_time_max_age=2.0,
        allow_stale_event_time=True,
    ).qualification
    assert qualification.trade_qualified_at_receipt is False
    assert "SOURCE_CLOCK_UNVERIFIED" in qualification.qualification_reasons
    assert "FRESHNESS_UNAVAILABLE" in qualification.qualification_reasons


def test_opt_in_keeps_freshness_unavailable_closed():
    qualification = qualify_market_tick_event(
        _event(
            freshness_status=MarketFreshnessStatus.UNAVAILABLE,
            freshness_reason_codes=("EVENT_TIME_AHEAD_OF_RECEIVE",),
            execution_eligible=False,
        ),
        event_time_max_age=2.0,
        allow_stale_event_time=True,
    ).qualification
    assert qualification.trade_qualified_at_receipt is False
    assert "FRESHNESS_UNAVAILABLE" in qualification.qualification_reasons
    assert "UPSTREAM_EXECUTION_INELIGIBLE" in qualification.qualification_reasons


def test_opt_in_keeps_event_time_after_receive_closed():
    qualification = qualify_market_tick_event(
        _event(
            provider_event_time_utc="2026-11-02T02:00:05.500000Z",
            execution_eligible=False,
            freshness_status=MarketFreshnessStatus.UNAVAILABLE,
            freshness_reason_codes=("EVENT_TIME_AHEAD_OF_RECEIVE",),
        ),
        event_time_max_age=2.0,
        allow_stale_event_time=True,
    ).qualification
    assert qualification.trade_qualified_at_receipt is False
    assert "EVENT_TIME_AFTER_RECEIVE" in qualification.qualification_reasons


def test_opt_in_requires_a_bool():
    with pytest.raises(MarketTickAdapterError, match="MARKET_TICK_EVENT_INVALID"):
        qualify_market_tick_event(
            _event(), event_time_max_age=2.0, allow_stale_event_time="yes"
        )
    with pytest.raises(MarketTickAdapterError, match="MARKET_TICK_EVENT_INVALID"):
        ingest_market_tick_event(
            _event(), event_time_max_age=2.0, allow_stale_event_time=1
        )


def test_base_contract_still_rejects_unmarked_stale_eligible_payload():
    with pytest.raises(market_tick_protocol.MarketTickContractError):
        _payload(
            quality_contract_ref="ctp.quote.v2",
            execution_eligible=True,
        )
