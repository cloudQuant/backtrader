"""Migration baseline for the SDK MarketTickEvent -> Backtrader tick projection.

Iteration 60 (opts line) requirement 60.01-R5: before the market tick
contracts are migrated, freeze the current observable behaviour of
``backtrader.feeds.market_tick_adapter`` so that later steps can prove the
projection did not change. These tests construct qualified and unqualified
SDK events from the public Base/SDK contracts only.
"""

from __future__ import annotations

import copy
import dataclasses

import pytest

market_tick_protocol = pytest.importorskip("bt_api_base.market_tick_protocol")
market_protocol = pytest.importorskip("bt_api_base.market_protocol")
pytest.importorskip("bt_api_py.market_tick_contracts")

from backtrader.feeds.market_tick_adapter import (  # noqa: E402
    MarketTickAdapterError,
    adapt_market_tick_event,
    is_market_tick_event_candidate,
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
        provider_event_time_utc="2026-11-02T02:00:00.500000Z",
        event_time_provenance="provider_reported",
        received_at_utc="2026-11-02T02:00:00.600000Z",
        received_monotonic_ns=123456789,
        provider_source="ctp.native.md",
        quality_contract_ref="ctp.quote.v2",
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
        freshness_status=MarketFreshnessStatus.FRESH,
        freshness_reason_codes=(),
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


def test_candidate_requires_exact_sdk_type():
    event = _event()
    assert is_market_tick_event_candidate(event) is True
    assert is_market_tick_event_candidate(dataclasses.asdict(event.data)) is False
    assert is_market_tick_event_candidate(object()) is False


def test_qualified_event_projection_baseline():
    event = _event()
    fields = adapt_market_tick_event(event)

    assert fields.sdk_market_tick is True
    assert fields.market_tick_event is event
    assert fields.symbol == fields.instrument_id == "SA609"
    assert fields.exchange == fields.venue == "CZCE"
    assert fields.provider == "ctp"
    assert fields.asset_type == "future"
    # Prices and sizes are copied 1:1 from the neutral payload.
    assert (fields.price, fields.last_price) == (1500.0, 1500.0)
    assert (fields.bid_price, fields.ask_price) == (1499.0, 1501.0)
    assert (fields.bid_volume, fields.ask_volume) == (10.0, 12.0)
    assert (fields.lower_limit_price, fields.upper_limit_price) == (1400.0, 1600.0)
    # Volume: the Backtrader "volume" line is the delta, never the cumulative.
    assert fields.volume == fields.delta_volume == 3.0
    assert fields.cum_volume == fields.cumulative_volume == 12345.0
    assert fields.volume_semantics == "delta"
    assert fields.bar_eligible is True
    # Clock and freshness facts.
    assert fields.data_clock_qualified is True
    assert fields.freshness_verified is True
    assert fields.stale is False
    assert fields.timestamp == fields.event_time_utc.timestamp()
    assert fields.event_time_utc.isoformat() == "2026-11-02T02:00:00.500000+00:00"
    assert fields.recv_time_utc.isoformat() == "2026-11-02T02:00:00.600000+00:00"
    # Source and cursor identity.
    assert fields.ingest_seq == fields.provider_sequence == 7
    assert fields.sequence == fields.cursor_sequence == 7
    assert fields.stream_id == SOURCE.stream_id
    assert fields.stream_epoch == "epoch-1"
    assert fields.connection_generation == 1
    assert fields.execution_eligible is True
    assert fields.quality == "GOOD"
    assert fields.quality_flags == []


def test_unknown_delta_volume_stays_unknown():
    fields = adapt_market_tick_event(_event(delta_volume=None, volume_complete=False))
    assert fields.volume is None
    assert fields.volume_semantics == "unknown"
    assert fields.bar_eligible is False


def test_quality_flags_mark_invalid():
    fields = adapt_market_tick_event(_event(quality_flags=("CROSSED_BOOK",)))
    assert fields.quality == "INVALID"
    assert fields.quality_flags == ["CROSSED_BOOK"]


@pytest.mark.parametrize(
    "overrides, code",
    [
        (
            dict(
                freshness_status=MarketFreshnessStatus.STALE,
                freshness_reason_codes=("AGE_EXCEEDED",),
                execution_eligible=False,
            ),
            "MARKET_DATA_STALE",
        ),
    ],
)
def test_unqualified_events_are_rejected(overrides, code):
    with pytest.raises(MarketTickAdapterError) as info:
        adapt_market_tick_event(_event(**overrides))
    assert info.value.code == code


def test_base_contract_rejects_stale_execution_eligible_payload():
    with pytest.raises(market_tick_protocol.MarketTickContractError):
        _payload(
            freshness_status=MarketFreshnessStatus.STALE,
            freshness_reason_codes=("AGE_EXCEEDED",),
            execution_eligible=True,
        )


def test_non_event_input_is_rejected():
    with pytest.raises(MarketTickAdapterError) as info:
        adapt_market_tick_event({"last_price": 1.0})
    assert info.value.code == "MARKET_TICK_EVENT_INVALID"


def test_projection_does_not_mutate_published_event():
    event = _event()
    before = copy.deepcopy(dataclasses.asdict(event.data))
    fields = adapt_market_tick_event(event)
    fields.quality_flags.append("LOCAL_FEED_FLAG")
    fields.volume = 999.0
    assert dataclasses.asdict(event.data) == before
    assert event.data.quality_flags == ()
