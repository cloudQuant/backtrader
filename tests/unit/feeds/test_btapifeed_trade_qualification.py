"""Iteration 62 (D62-15b/21/27/28/37): data lines vs. live-order qualification.

A real-time typed SDK tick with a parseable provider event time and local
receive time enters bars, lines and indicators in order even when its clocks
are not verified, its freshness is unavailable or stale, or its latency is
over the limit. Whether the feed may back a live order is a separate,
explicit verdict, ``BtApiFeed.trade_qualification()``, re-computed against
the current monotonic clock on every call. Ticks with missing times are
ingestion errors: dropped and counted, never given a substituted time, and
they never raise out of the feed.

Ticks are built from the public Base/SDK dataclasses only
(``bind_market_tick_event`` with a ``MarketSourceDescriptor``). Evidence
level: UNIT/FAKE (in-process fake Store, injected monotonic clock).
"""

from __future__ import annotations

import collections
import dataclasses
import datetime as dt
import logging

import pytest

pytest.importorskip("bt_api_py.market_tick_contracts")

import backtrader as bt  # noqa: E402
from backtrader.feeds import btapifeed as btapifeed_module  # noqa: E402
from backtrader.feeds.btapifeed import BtApiFeed, FeedTradeQualification  # noqa: E402
from backtrader.feeds.market_tick_adapter import (  # noqa: E402
    MarketTickAdapterError,
    adapt_market_tick_event,
    ingest_market_tick_event,
)
from backtrader.utils import log_message  # noqa: E402
from tests.unit.feeds import test_market_tick_adapter_baseline as typed  # noqa: E402

T0 = dt.datetime(2026, 11, 2, 2, 0, tzinfo=dt.timezone.utc)
MONO0 = 5_000_000_000_000  # receive monotonic ns of a tick at T0
NS = 1_000_000_000

UNQUALIFIED = dict(
    source_clock_quality=typed.MarketClockQuality.UNKNOWN,
    receive_clock_quality=typed.MarketClockQuality.UNKNOWN,
    source_clock_error_ms=None,
    receive_clock_error_ms=None,
    freshness_status=typed.MarketFreshnessStatus.UNAVAILABLE,
    freshness_reason_codes=("SOURCE_CLOCK_CALIBRATION_NOT_PROVIDED",),
    execution_eligible=False,
)


def _utc_text(moment):
    return moment.isoformat().replace("+00:00", "Z")


def _event(sequence, second, *, latency=0.1, price=1500.0, **overrides):
    """One bound SDK tick; event at ``T0 + second``, received ``latency`` later."""
    event_time = T0 + dt.timedelta(seconds=second)
    values = dict(
        last_price=price,
        provider_event_time_utc=_utc_text(event_time),
        received_at_utc=_utc_text(event_time + dt.timedelta(seconds=latency)),
        received_monotonic_ns=MONO0 + int((second + latency) * NS),
        provider_sequence=sequence,
    )
    values.update(overrides)
    return typed.bind_market_tick_event(
        typed._payload(**values),
        typed.SOURCE,
        typed.MarketEventCursor(
            stream_id=typed.SOURCE.stream_id, epoch=typed.SOURCE.epoch, sequence=sequence
        ),
    )


def _receipt_ns(second, latency=0.1):
    return MONO0 + int((second + latency) * NS)


class _Store:
    """In-process stand-in for a started BtApiStore tick source."""

    def __init__(self):
        self.ticks = collections.deque()
        self.dropped = []

    def start(self, data=None):
        pass

    def register(self, feed):
        pass

    def subscribe(self, *_args, **_kwargs):
        pass

    def poll_tick(self, _name):
        return self.ticks.popleft() if self.ticks else None

    def poll_live(self, _name):
        return None

    def mark_feed_dropped(self, event, reason):
        self.dropped.append((event.symbol, reason))


class _Clock:
    """Injected feed clock; ``mono`` is the current monotonic time in ns."""

    def __init__(self, mono):
        self.mono = mono

    def monotonic_ns(self):
        return self.mono


@pytest.fixture
def harness():
    store = _Store()
    clock = _Clock(_receipt_ns(0))
    feed = BtApiFeed(
        dataname="SA609",
        store=store,
        timeframe=bt.TimeFrame.Minutes,
        compression=1,
        price_tick=1.0,
        backfill_start=False,
        clock=clock,
        qcheck=0.0,
    )
    feed._start()  # what Cerebro calls: start() plus the line/timezone setup
    yield feed, store, clock
    feed.stop()


def _statuses(feed):
    return [status for status, _args, _kwargs in feed.get_notifications()]


def _feed_ticks(feed, store, clock, *events):
    """Queue events, advance the clock to the last receipt, run one load turn."""
    store.ticks.extend(events)
    clock.mono = max(clock.mono, max(event.data.received_monotonic_ns or 0 for event in events))
    return feed.load()


# -- data lines ---------------------------------------------------------------


def test_unqualified_ticks_still_build_and_publish_bars(harness):
    feed, store, clock = harness
    assert _feed_ticks(feed, store, clock, _event(8, 10, **UNQUALIFIED)) is None
    # The next minute's tick moves the event-time watermark past minute 0.
    assert _feed_ticks(feed, store, clock, _event(9, 70, price=1501.0, **UNQUALIFIED)) is True
    assert feed.close[0] == 1500.0
    assert feed.datetime.datetime(0) == T0.replace(tzinfo=None)
    # The line value is real data but not a trusted valuation mark.
    assert feed._valuation_bar[3] == "local_aggregation_unqualified"
    with pytest.raises(ValueError) as info:
        feed.valuation_mark()
    assert info.value.code == "MARK_SOURCE_UNTRUSTED"
    assert feed.tick_ingest_error_counts() == {}


def test_stale_but_complete_ticks_enter_lines(harness):
    feed, store, clock = harness
    stale = dict(
        freshness_status=typed.MarketFreshnessStatus.STALE,
        freshness_reason_codes=("AGE_EXCEEDED",),
        execution_eligible=False,
    )
    _feed_ticks(feed, store, clock, _event(8, 10, latency=5.0, **stale))
    assert _feed_ticks(feed, store, clock, _event(9, 70, latency=5.0, **stale)) is True
    assert feed.close[0] == 1500.0
    verdict = feed.trade_qualification()
    assert verdict.ok is False
    assert {"FRESHNESS_STALE", "EVENT_TIME_STALE"} <= set(verdict.reasons)


def test_qualified_tick_projection_and_gates_match_the_strict_adapter():
    """Gateway/managed sources deliver qualified ticks: their handling is unchanged."""
    event = _event(8, 10)
    strict = adapt_market_tick_event(event)
    result = ingest_market_tick_event(event, event_time_max_age=2.0)
    assert result.error_code is None
    admitted = vars(result.tick).copy()
    assert admitted.pop("trade_qualified_at_receipt") is True
    assert admitted.pop("qualification_reasons") == ()
    assert admitted == vars(strict)

    def prepared(tick):
        feed = BtApiFeed(
            dataname="SA609",
            store=None,
            timeframe=bt.TimeFrame.Minutes,
            compression=1,
            price_tick=1.0,
            clock=_Clock(_receipt_ns(10)),
        )
        feed._prepare_tick(tick)
        return (tick.quality, tick.quality_flags, tick.execution_eligible, tick.bar_eligible)

    assert prepared(result.tick) == prepared(adapt_market_tick_event(event))
    assert prepared(result.tick) == ("GOOD", (), True, True)


@pytest.mark.parametrize(
    "latency, overrides, reason",
    [
        (2.5, {}, "EVENT_TIME_STALE"),
        (-0.2, {}, "EVENT_TIME_AFTER_RECEIVE"),
        (0.1, UNQUALIFIED, "SOURCE_CLOCK_UNVERIFIED"),
        (0.1, dict(execution_eligible=False), "UPSTREAM_EXECUTION_INELIGIBLE"),
    ],
)
def test_admitted_unqualified_ticks_are_never_execution_eligible(latency, overrides, reason):
    """Only data-integrity flags are relaxed; execution (and broker tick routing) is not."""
    result = ingest_market_tick_event(
        _event(8, 10, latency=latency, **overrides), event_time_max_age=2.0
    )
    tick = result.tick
    assert tick.trade_qualified_at_receipt is False
    assert reason in tick.qualification_reasons
    feed = BtApiFeed(
        dataname="SA609",
        store=None,
        timeframe=bt.TimeFrame.Minutes,
        compression=1,
        price_tick=1.0,
        clock=_Clock(_receipt_ns(10, latency)),
    )
    feed._prepare_tick(tick)
    assert reason in tick.quality_flags
    assert tick.execution_eligible is False
    assert tick.quality == "INVALID"
    assert tick.data_quality == "GOOD"
    assert tick.bar_eligible is True


@pytest.mark.parametrize(
    "overrides, source",
    [({}, "market_tick"), (UNQUALIFIED, "market_tick_unqualified")],
)
def test_tick_timeframe_lines_label_unqualified_ticks(overrides, source):
    store = _Store()
    clock = _Clock(_receipt_ns(10))
    feed = BtApiFeed(
        dataname="SA609",
        store=store,
        timeframe=bt.TimeFrame.Ticks,
        price_tick=1.0,
        backfill_start=False,
        clock=clock,
        qcheck=0.0,
    )
    feed._start()
    try:
        store.ticks.append(_event(8, 10, **overrides))
        assert feed.load() is True
        assert feed.close[0] == 1500.0
        assert feed._valuation_bar[3] == source
    finally:
        feed.stop()


def test_strict_adapter_still_rejects_unverified_clocks():
    with pytest.raises(MarketTickAdapterError) as info:
        adapt_market_tick_event(_event(8, 10, **UNQUALIFIED))
    assert info.value.code == "TICK_CLOCK_UNAVAILABLE"


# -- trade qualification ------------------------------------------------------


def test_qualified_fresh_tick_makes_the_feed_trade_qualified(harness):
    feed, store, clock = harness
    _feed_ticks(feed, store, clock, _event(8, 10, latency=0.1))
    clock.mono = _receipt_ns(10) + NS // 2
    verdict = feed.trade_qualification()
    assert isinstance(verdict, FeedTradeQualification)
    assert verdict.ok is True
    assert verdict.reasons == ()
    assert verdict.live is True
    assert verdict.last_event_time_utc == T0 + dt.timedelta(seconds=10)
    assert verdict.last_received_at_utc == T0 + dt.timedelta(seconds=10.1)
    assert verdict.receive_age_seconds == pytest.approx(0.5)
    with pytest.raises(dataclasses.FrozenInstanceError):
        verdict.ok = False


@pytest.mark.parametrize(
    "latency, qualified",
    [(1.8, True), (2.0, True), (2.5, False)],
)
def test_event_latency_is_compared_directly_with_its_limit(harness, latency, qualified):
    feed, store, clock = harness
    _feed_ticks(feed, store, clock, _event(8, 10, latency=latency))
    verdict = feed.trade_qualification()
    assert verdict.ok is qualified
    assert ("EVENT_TIME_STALE" in verdict.reasons) is (not qualified)
    # Either way the tick is in the open bar: staleness never drops data.
    assert len(feed._bar_builders) == 1


def test_event_time_after_receipt_is_not_trade_qualified(harness):
    feed, store, clock = harness
    _feed_ticks(feed, store, clock, _event(8, 10, latency=-0.2))
    verdict = feed.trade_qualification()
    assert verdict.ok is False
    assert "EVENT_TIME_AFTER_RECEIVE" in verdict.reasons
    assert len(feed._bar_builders) == 1


def test_quiet_market_expires_the_last_qualified_tick(harness):
    feed, store, clock = harness
    _feed_ticks(feed, store, clock, _event(8, 10))
    receipt = _receipt_ns(10)
    assert feed.trade_qualification(now_monotonic_ns=receipt + 2 * NS).ok is True
    stale = feed.trade_qualification(now_monotonic_ns=receipt + 2 * NS + 1)
    assert stale.ok is False
    assert stale.reasons == ("RECEIVE_TIME_STALE",)
    assert stale.live is True  # LIVE status is reported separately
    # Without an argument the feed's own clock is read on every call.
    clock.mono = receipt + 3 * NS
    assert feed.trade_qualification().reasons == ("RECEIVE_TIME_STALE",)
    # A new qualified tick restores the verdict.
    _feed_ticks(feed, store, clock, _event(9, 15))
    clock.mono = _receipt_ns(15)
    assert feed.trade_qualification().ok is True


def test_latest_tick_decides_and_unqualified_reasons_are_reported(harness):
    feed, store, clock = harness
    _feed_ticks(feed, store, clock, _event(8, 10))
    assert feed.trade_qualification().ok is True
    _feed_ticks(feed, store, clock, _event(9, 11, **UNQUALIFIED))
    verdict = feed.trade_qualification()
    assert verdict.ok is False
    assert verdict.reasons == (
        "SOURCE_CLOCK_UNVERIFIED",
        "RECEIVE_CLOCK_UNVERIFIED",
        "FRESHNESS_UNAVAILABLE",
        "UPSTREAM_EXECUTION_INELIGIBLE",
    )
    _feed_ticks(feed, store, clock, _event(10, 12))
    assert feed.trade_qualification().ok is True


def test_no_trade_qualification_before_realtime_ticks_or_after_stop(harness):
    feed, store, clock = harness
    verdict = feed.trade_qualification()
    assert verdict.ok is False
    assert verdict.reasons == ("FEED_NOT_LIVE", "REALTIME_TICK_UNAVAILABLE")
    assert verdict.receive_age_seconds is None
    _feed_ticks(feed, store, clock, _event(8, 10))
    assert feed.trade_qualification().ok is True
    feed.stop()
    after = feed.trade_qualification()
    assert after.ok is False
    assert after.reasons == ("FEED_NOT_LIVE", "REALTIME_TICK_UNAVAILABLE")


@pytest.mark.parametrize(
    "now, reason",
    [(1.5, "NOW_MONOTONIC_INVALID"), (True, "NOW_MONOTONIC_INVALID"), (1, "RECEIVE_AGE_INVALID")],
)
def test_unusable_now_fails_closed_with_a_finite_reason(harness, now, reason):
    feed, store, clock = harness
    _feed_ticks(feed, store, clock, _event(8, 10))
    verdict = feed.trade_qualification(now_monotonic_ns=now)
    assert verdict.ok is False
    assert verdict.reasons == (reason,)


def test_invalid_receive_age_limit_fails_closed(harness):
    feed, store, clock = harness
    _feed_ticks(feed, store, clock, _event(8, 10))
    feed.p.receive_time_max_age = None
    assert feed.trade_qualification().reasons == ("RECEIVE_TIME_MAX_AGE_INVALID",)


# -- ingestion errors -----------------------------------------------------------

_NO_EVENT_TIME = dict(
    UNQUALIFIED, provider_event_time_utc=None, event_time_provenance="unavailable"
)


@pytest.mark.parametrize(
    "overrides, code",
    [
        (_NO_EVENT_TIME, "TICK_EVENT_TIME_UNAVAILABLE"),
        (dict(UNQUALIFIED, received_at_utc=None), "TICK_RECEIVE_TIME_UNAVAILABLE"),
        (dict(UNQUALIFIED, received_monotonic_ns=None), "TICK_RECEIVE_MONOTONIC_UNAVAILABLE"),
    ],
)
def test_ticks_with_missing_times_are_dropped_counted_and_never_raise(harness, overrides, code):
    feed, store, clock = harness
    first, second = _event(8, 10, **overrides), _event(9, 11, **overrides)
    assert _feed_ticks(feed, store, clock, first, second) is None
    assert feed.tick_ingest_error_counts() == {code: 2}
    assert store.dropped == [("SA609", code.lower())] * 2
    assert feed._bar_builders == {}
    assert feed.LIVE not in _statuses(feed)  # dropped ticks are not real-time traffic
    verdict = feed.trade_qualification()
    assert verdict.ok is False
    assert code in verdict.reasons
    assert verdict.last_event_time_utc is None


def test_an_ingestion_error_after_a_qualified_tick_withholds_qualification(harness):
    feed, store, clock = harness
    _feed_ticks(feed, store, clock, _event(8, 10))
    assert feed.trade_qualification().ok is True
    _feed_ticks(feed, store, clock, _event(9, 11, **_NO_EVENT_TIME))
    verdict = feed.trade_qualification()
    assert verdict.ok is False
    assert verdict.reasons == ("TICK_EVENT_TIME_UNAVAILABLE",)
    assert verdict.last_event_time_utc == T0 + dt.timedelta(seconds=10)
    _feed_ticks(feed, store, clock, _event(10, 12))
    assert feed.trade_qualification().ok is True


@pytest.fixture
def warnings_log(monkeypatch):
    records = []

    class _ListHandler(logging.Handler):
        def emit(self, record):
            records.append(record.getMessage())

    handler = _ListHandler(level=logging.WARNING)
    logger = btapifeed_module.logger
    monkeypatch.setattr(log_message, "_throttle_state", {})
    monkeypatch.setattr(logger, "level", logging.WARNING)
    logger.addHandler(handler)
    yield records
    logger.removeHandler(handler)


def test_ingestion_errors_log_once_per_reason(harness, warnings_log):
    feed, store, clock = harness
    _feed_ticks(feed, store, clock, *(_event(seq, seq, **_NO_EVENT_TIME) for seq in range(1, 6)))
    _feed_ticks(
        feed,
        store,
        clock,
        *(_event(seq, seq, **dict(UNQUALIFIED, received_at_utc=None)) for seq in range(6, 9)),
    )
    dropped = [message for message in warnings_log if "dropped real-time tick" in message]
    assert len(dropped) == 2
    assert "TICK_EVENT_TIME_UNAVAILABLE" in dropped[0]
    assert "TICK_RECEIVE_TIME_UNAVAILABLE" in dropped[1]
    assert feed.tick_ingest_error_counts() == {
        "TICK_EVENT_TIME_UNAVAILABLE": 5,
        "TICK_RECEIVE_TIME_UNAVAILABLE": 3,
    }


# -- feed status --------------------------------------------------------------


def test_clock_unverified_ticks_emit_live_and_never_delayed(harness):
    feed, store, clock = harness
    stale = dict(
        freshness_status=typed.MarketFreshnessStatus.STALE,
        freshness_reason_codes=("AGE_EXCEEDED",),
        execution_eligible=False,
    )
    _feed_ticks(feed, store, clock, _event(8, 10, latency=4.0, **stale))  # received at 14 s
    _feed_ticks(feed, store, clock, _event(9, 14, **UNQUALIFIED))
    _feed_ticks(feed, store, clock, _event(10, 15, execution_eligible=False))
    assert _statuses(feed) == [feed.LIVE]
    assert feed._continuity_degraded is False
    verdict = feed.trade_qualification()
    assert verdict.live is True
    assert verdict.ok is False
    assert verdict.reasons == ("UPSTREAM_EXECUTION_INELIGIBLE",)


@pytest.mark.parametrize(
    "overrides",
    [
        dict(UNQUALIFIED, continuity_status="gap"),
        dict(UNQUALIFIED, quality_flags=("CROSSED_BOOK",)),
    ],
    ids=["continuity_gap", "data_defect"],
)
def test_continuity_and_data_defects_still_degrade_the_feed(harness, overrides):
    feed, store, clock = harness
    _feed_ticks(feed, store, clock, _event(8, 10))
    assert _statuses(feed) == [feed.LIVE]
    _feed_ticks(feed, store, clock, _event(9, 11, **overrides))
    assert _statuses(feed) == [feed.DELAYED]
    assert feed._continuity_degraded is True
    verdict = feed.trade_qualification()
    assert verdict.live is False
    assert "FEED_NOT_LIVE" in verdict.reasons


def test_historical_backfill_is_not_live_and_realtime_ticks_are():
    history = {
        "datetime": T0.replace(tzinfo=None) - dt.timedelta(minutes=1),
        "open": 1490.0,
        "high": 1495.0,
        "low": 1489.0,
        "close": 1494.0,
        "volume": 7.0,
        "openinterest": 0.0,
        "bar_final": True,
    }
    store = _Store()
    clock = _Clock(_receipt_ns(10))
    feed = BtApiFeed(
        dataname="SA609",
        store=store,
        timeframe=bt.TimeFrame.Minutes,
        compression=1,
        price_tick=1.0,
        backfill_start=False,
        historical_bars=[history],
        clock=clock,
        qcheck=0.0,
    )
    feed._start()
    try:
        store.ticks.append(_event(8, 10, **UNQUALIFIED))
        assert feed.load() is True
        assert feed.close[0] == 1494.0
        assert feed.LIVE not in _statuses(feed)
        assert feed.trade_qualification().live is False
        assert feed.load() is None  # drains the queued real-time tick
        assert _statuses(feed) == [feed.LIVE]
        assert feed.trade_qualification().live is True
    finally:
        feed.stop()


def test_historical_warmup_is_active_only_while_history_is_pending(harness):
    feed, _store, _clock = harness
    assert feed.historical_warmup_active() is False
    feed._history.append(object())
    assert feed.historical_warmup_active() is True
    feed._history.clear()
    assert feed.historical_warmup_active() is False
