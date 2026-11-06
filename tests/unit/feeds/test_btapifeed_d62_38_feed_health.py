"""Iteration 62, D62-38 (user decisions 2026-11-06): what degrades a BtApiFeed.

Feed health (LIVE/DELAYED) and ``trade_qualification()`` gate only on price
freshness, the current connection without local message loss, quote validity
and the trading phase. Volume accounting, bar construction and quote-shape
warnings never degrade the feed by themselves:

* the provider BASELINE shape (``continuous`` + incomplete volume, size 0 or
  above) and a volume reset flagged ``VOLUME_DISCONTINUITY`` stay LIVE;
* incomplete volume under any attested continuity is a bar-only flag; a
  ``gap`` or unknown continuity still degrades;
* the first ticks of a newer connection scope, and a tick that arrives behind
  the event-time watermark, stay LIVE (their bars are handled as before); a
  retired scope still degrades;
* a one-sided book exactly at this snapshot's own limit price, a locked book
  and zero depth are warnings (``quality_warnings`` on the bar); a near miss,
  both sides missing, a crossed book or a provider quality failure still
  degrade.

Ticks are built from the public Base/SDK dataclasses only. Evidence level:
UNIT/FAKE (in-process fake Store, injected monotonic clock).
"""

from __future__ import annotations

import dataclasses
import datetime as dt

import pytest

pytest.importorskip("bt_api_py.market_tick_contracts")

import backtrader as bt  # noqa: E402
from backtrader.feeds.btapifeed import BtApiFeed  # noqa: E402
from backtrader.feeds.market_tick_adapter import ingest_market_tick_event  # noqa: E402
from tests.unit.feeds import test_market_tick_adapter_baseline as typed  # noqa: E402
from tests.unit.feeds.test_btapifeed_trade_qualification import (  # noqa: E402
    NS,
    T0,
    MONO0,
    _Clock,
    _event,
    _feed_ticks,
    _receipt_ns,
    _statuses,
    _Store,
    _utc_text,
)

# The provider shapes of D62-38 (bt_api_ctp/okx/binance after the change).
BASELINE = dict(
    continuity_status="continuous",
    volume_complete=False,
    volume_quality="BASELINE",
    delta_volume=0.0,
)
BASELINE_WITH_SIZE = dict(BASELINE, delta_volume=2.0)
VOLUME_RESET = dict(
    BASELINE, volume_quality="VOLUME_RESET", quality_flags=("VOLUME_DISCONTINUITY",)
)


def _event_scope(sequence, second, *, generation, epoch=1, latency=0.1, price=1500.0, **values):
    """One bound SDK tick of connection ``generation`` / subscription ``epoch``."""
    source = dataclasses.replace(typed.SOURCE, connection_generation=generation)
    event_time = T0 + dt.timedelta(seconds=second)
    payload = dict(
        last_price=price,
        provider_event_time_utc=_utc_text(event_time),
        received_at_utc=_utc_text(event_time + dt.timedelta(seconds=latency)),
        received_monotonic_ns=MONO0 + int((second + latency) * NS),
        provider_sequence=sequence,
        provider_connection_generation=generation,
        provider_subscription_epoch=epoch,
    )
    payload.update(values)
    return typed.bind_market_tick_event(
        typed._payload(**payload),
        source,
        typed.MarketEventCursor(stream_id=source.stream_id, epoch=source.epoch, sequence=sequence),
    )


@pytest.fixture
def feed_with_bars():
    """A started Minutes feed whose completed bar events are recorded."""
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
    feed._start()
    bars = []
    enqueue = feed._enqueue_bar_event

    def record(bar_event, bar_datetime, *, deliver_lines=True, bar_source=None):
        bars.append((bar_event, deliver_lines))
        return enqueue(bar_event, bar_datetime, deliver_lines=deliver_lines, bar_source=bar_source)

    feed._enqueue_bar_event = record
    yield feed, store, clock, bars
    feed.stop()


def _prepared(event, receipt_second, *, cohort=False):
    tick = ingest_market_tick_event(event, event_time_max_age=2.0).tick
    feed = BtApiFeed(
        dataname="SA609",
        store=None,
        timeframe=bt.TimeFrame.Minutes,
        compression=1,
        price_tick=1.0,
        clock=_Clock(_receipt_ns(receipt_second)),
    )
    if cohort:
        feed._live_bar_cohort = object()  # only the strict-classification switch
    feed._prepare_tick(tick)
    return tick, feed


def _assert_live_and_tradable(feed):
    assert feed._continuity_degraded is False
    verdict = feed.trade_qualification()
    assert verdict.live is True
    assert verdict.ok is True, verdict.reasons


# -- volume accounting (decision 1) --------------------------------------------


@pytest.mark.parametrize("shape", [BASELINE, BASELINE_WITH_SIZE], ids=["size0", "size_gt0"])
def test_baseline_shape_first_tick_is_live_and_tradable(feed_with_bars, shape):
    feed, store, clock, _bars = feed_with_bars
    _feed_ticks(feed, store, clock, _event(1, 10, **shape))
    assert _statuses(feed) == [feed.LIVE]
    _assert_live_and_tradable(feed)


def test_baseline_shape_after_a_trading_day_change_stays_live(feed_with_bars):
    feed, store, clock, _bars = feed_with_bars
    _feed_ticks(feed, store, clock, _event(1, 10), _event(2, 11))
    assert _statuses(feed) == [feed.LIVE]
    _feed_ticks(feed, store, clock, _event(3, 12, trading_date="2026-11-03", **BASELINE))
    assert _statuses(feed) == []
    _assert_live_and_tradable(feed)


def test_volume_reset_flagged_discontinuity_stays_live_and_marks_its_bar(feed_with_bars):
    feed, store, clock, bars = feed_with_bars
    _feed_ticks(feed, store, clock, _event(1, 10))
    assert _statuses(feed) == [feed.LIVE]
    _feed_ticks(feed, store, clock, _event(2, 11, cumulative_volume=10.0, **VOLUME_RESET))
    assert _statuses(feed) == []  # was DELAYED: VOLUME_DISCONTINUITY blocked
    _assert_live_and_tradable(feed)
    _feed_ticks(feed, store, clock, _event(3, 12, cumulative_volume=13.0))
    _feed_ticks(feed, store, clock, _event(4, 70, cumulative_volume=16.0))
    bar, _deliver = bars[0]
    assert "VOLUME_DISCONTINUITY" in bar.quality_flags
    assert bar.complete is False


@pytest.mark.parametrize("continuity", ["snapshot", "ok", "recovered"])
def test_incomplete_volume_under_attested_continuity_is_bar_only(continuity):
    jump = dict(continuity_status=continuity, volume_complete=False, delta_volume=4.0)
    tick, feed = _prepared(_event(9, 11, cumulative_volume=None, **jump), 11)
    assert tick.quality_flags == ("VOLUME_INCOMPLETE",)
    assert (tick.quality, tick.data_quality) == ("GOOD", "GOOD")
    assert tick.bar_eligible is True
    assert feed._handle_event_health(tick) is False


@pytest.mark.parametrize("continuity", ["gap", "unknown"])
def test_incomplete_volume_without_attested_continuity_still_blocks(continuity):
    jump = dict(continuity_status=continuity, volume_complete=False, delta_volume=4.0)
    tick, feed = _prepared(_event(9, 11, cumulative_volume=None, **jump), 11)
    assert tick.data_quality == "INVALID"
    assert tick.bar_eligible is False


def test_gap_continuity_still_degrades_the_feed(feed_with_bars):
    feed, store, clock, _bars = feed_with_bars
    _feed_ticks(feed, store, clock, _event(1, 10))
    gap = dict(VOLUME_RESET, continuity_status="gap")
    _feed_ticks(feed, store, clock, _event(2, 11, **gap))
    assert _statuses(feed) == [feed.LIVE, feed.DELAYED]
    assert "FEED_NOT_LIVE" in feed.trade_qualification().reasons


def test_cohort_keeps_the_strict_rule_for_attested_non_continuous_continuity():
    jump = dict(continuity_status="snapshot", volume_complete=False, delta_volume=4.0)
    tick, _feed = _prepared(_event(9, 11, cumulative_volume=None, **jump), 11, cohort=True)
    assert tick.data_quality == "INVALID"


# -- connection scope and bar construction (decision 1) ------------------------


def test_reconnect_baseline_ticks_keep_the_feed_live(feed_with_bars):
    feed, store, clock, bars = feed_with_bars
    _feed_ticks(feed, store, clock, _event_scope(1, 10, generation=1))
    assert _statuses(feed) == [feed.LIVE]
    # The provider reconnected: the first tick of generation 2 is a baseline in
    # the same minute, whose open bar is invalidated (not on the lines).
    _feed_ticks(feed, store, clock, _event_scope(1, 20, generation=2, **BASELINE))
    _feed_ticks(feed, store, clock, _event_scope(2, 21, generation=2))
    assert _statuses(feed) == []  # was DELAYED until the next minute
    _assert_live_and_tradable(feed)
    assert [(bar.complete, deliver) for bar, deliver in bars] == [(False, False)]
    assert "FORCED_INVALIDATION" in bars[0][0].quality_flags
    _feed_ticks(feed, store, clock, _event_scope(3, 70, generation=2))
    _feed_ticks(feed, store, clock, _event_scope(4, 130, generation=2))
    assert _statuses(feed) == []
    assert [(bar.complete, deliver) for bar, deliver in bars[1:]] == [(True, True)]


def test_retired_scope_tick_still_degrades(feed_with_bars):
    feed, store, clock, _bars = feed_with_bars
    _feed_ticks(feed, store, clock, _event_scope(1, 10, generation=2))
    assert _statuses(feed) == [feed.LIVE]
    _feed_ticks(feed, store, clock, _event_scope(2, 11, generation=1))
    assert _statuses(feed) == [feed.DELAYED]
    assert "FEED_NOT_LIVE" in feed.trade_qualification().reasons


def test_tick_behind_the_watermark_does_not_degrade(feed_with_bars):
    feed, store, clock, bars = feed_with_bars
    _feed_ticks(feed, store, clock, _event(1, 10, latency=0.1))
    assert _statuses(feed) == [feed.LIVE]
    # In order (59.9 > 10) but its latency jitter puts the watermark
    # (10 + 50.8 s elapsed) past the minute's deadline: late for its bar.
    _feed_ticks(feed, store, clock, _event(2, 59.9, latency=1.0))
    assert _statuses(feed) == []  # was DELAYED
    _assert_live_and_tradable(feed)
    _feed_ticks(feed, store, clock, _event(3, 70))  # closes minute 0
    assert _statuses(feed) == []
    ((bar, deliver),) = bars
    assert "LATE_AFTER_WATERMARK" in bar.quality_flags
    assert (bar.volume, deliver) == (3.0, False)  # the late tick is not in it


# -- quote validity and warnings (decision 4) ----------------------------------

LIMIT_UP = dict(
    last_price=1600.0,
    bid_price=1600.0,
    bid_size=50.0,
    ask_price=0.0,  # CTP DBL_MAX sentinel as transported
    ask_size=0.0,
    upper_limit=1600.0,
    lower_limit=1400.0,
)
LIMIT_DOWN = dict(
    last_price=1400.0,
    bid_price=0.0,
    bid_size=0.0,
    ask_price=1400.0,
    ask_size=40.0,
    upper_limit=1600.0,
    lower_limit=1400.0,
)


@pytest.mark.parametrize(
    "shape, side, missing",
    [
        (LIMIT_UP, "UP", "ASK"),
        (dict(LIMIT_UP, ask_price=None), "UP", "ASK"),
        (LIMIT_DOWN, "DOWN", "BID"),
        (dict(LIMIT_DOWN, bid_price=None), "DOWN", "BID"),
    ],
    ids=["up", "up_none", "down", "down_none"],
)
def test_one_sided_book_at_the_limit_is_a_valid_quote(shape, side, missing):
    values = dict(shape)
    price = values.pop("last_price")
    tick, feed = _prepared(_event(1, 10, price=price, **values), 10)
    assert f"LIMIT_LOCKED_{side}" in tick.quality_flags
    assert f"{missing}_DEPTH_ZERO" in tick.quality_flags
    assert f"{missing}_PRICE_INVALID" not in tick.quality_flags
    assert (tick.quality, tick.data_quality, tick.bar_eligible) == ("GOOD", "GOOD", True)
    assert feed._handle_event_health(tick) is False


def test_limit_locked_ticks_keep_the_feed_live_and_build_a_complete_bar(feed_with_bars):
    feed, store, clock, bars = feed_with_bars
    values = dict(LIMIT_UP)
    price = values.pop("last_price")
    _feed_ticks(feed, store, clock, _event(1, 10, price=price, **values))
    _feed_ticks(feed, store, clock, _event(2, 11, price=price, **values))
    assert _statuses(feed) == [feed.LIVE]
    _assert_live_and_tradable(feed)
    _feed_ticks(feed, store, clock, _event(3, 70, price=price, **values))
    ((bar, deliver),) = bars
    assert (bar.complete, bar.quality, bar.quality_flags, deliver) == (True, "GOOD", (), True)
    assert bar.quality_warnings == ("ASK_DEPTH_ZERO", "LIMIT_LOCKED_UP")
    assert feed.close[0] == 1600.0


@pytest.mark.parametrize(
    "override",
    [
        dict(bid_price=1599.0),  # near miss: not at the limit
        dict(bid_price=0.0, bid_size=0.0),  # both sides missing
        dict(ask_size=5.0),  # an ask size without an ask price
        dict(upper_limit=None),  # limit unknown
        dict(price=1601.0),  # last price outside the limits
    ],
    ids=["near_miss", "both_missing", "ask_size", "limit_unknown", "last_above_limit"],
)
def test_other_one_sided_books_stay_invalid(override):
    values = dict(LIMIT_UP)
    price = values.pop("last_price")
    values.update(override)
    price = values.pop("price", price)
    tick, feed = _prepared(_event(1, 10, price=price, **values), 10)
    assert not any(flag.startswith("LIMIT_LOCKED") for flag in tick.quality_flags)
    assert tick.data_quality == "INVALID"
    assert feed._handle_event_health(tick) is True


@pytest.mark.parametrize(
    "values",
    [
        dict(quality_flags=("LOCKED_BOOK",), bid_price=1500.0, ask_price=1500.0),
        dict(quality_flags=("ZERO_DEPTH",), bid_size=0.0),
        dict(bid_size=0.0),
        dict(ask_size=0.0),
    ],
    ids=["provider_locked", "provider_zero_depth", "bid_depth_zero", "ask_depth_zero"],
)
def test_locked_book_and_zero_depth_are_warnings(feed_with_bars, values):
    feed, store, clock, bars = feed_with_bars
    _feed_ticks(feed, store, clock, _event(1, 10, **values), _event(2, 11, **values))
    assert _statuses(feed) == [feed.LIVE]
    _assert_live_and_tradable(feed)
    _feed_ticks(feed, store, clock, _event(3, 70))
    ((bar, deliver),) = bars
    assert (bar.complete, bar.quality_flags, deliver) == (True, (), True)
    assert bar.quality_warnings


@pytest.mark.parametrize(
    "values",
    [
        dict(quality_flags=("PROVIDER_QUALITY_FAILURE",)),
        dict(quality_flags=("CROSSED_BOOK",)),
        dict(bid_price=1502.0),  # crossed: bid above ask
        # Today's CTP limit-lock shape: provider-declared invalid quote, gap.
        dict(LIMIT_UP, quality_flags=("PROVIDER_QUALITY_FAILURE",), continuity_status="gap"),
    ],
    ids=["provider_failure", "provider_crossed", "crossed", "ctp_shape_today"],
)
def test_invalid_quotes_still_degrade(feed_with_bars, values):
    feed, store, clock, _bars = feed_with_bars
    _feed_ticks(feed, store, clock, _event(1, 10))
    values = dict(values)
    price = values.pop("last_price", 1500.0)
    _feed_ticks(feed, store, clock, _event(2, 11, price=price, **values))
    assert _statuses(feed) == [feed.LIVE, feed.DELAYED]
    assert "FEED_NOT_LIVE" in feed.trade_qualification().reasons


def test_cohort_keeps_quote_warnings_blocking():
    tick, _feed = _prepared(_event(1, 10, quality_flags=("LOCKED_BOOK",)), 10, cohort=True)
    assert tick.data_quality == "INVALID"


# -- exchange time going backwards (decision 3) ---------------------------------


def _reasons(store):
    return [reason for _symbol, reason in store.dropped]


def test_single_backwards_tick_is_dropped_without_degrading(feed_with_bars):
    feed, store, clock, bars = feed_with_bars
    _feed_ticks(feed, store, clock, _event(1, 10))
    assert _statuses(feed) == [feed.LIVE]
    first = feed.trade_qualification()
    watermark_state = (feed._max_event_timestamp, feed._last_ingest_monotonic_ns)
    # An older snapshot re-delivered 2 s later (received after the first one).
    _feed_ticks(feed, store, clock, _event(2, 8, latency=4.0))
    assert _statuses(feed) == []  # was DELAYED
    _assert_live_and_tradable(feed)
    assert feed.tick_ingest_error_counts() == {"OUT_OF_ORDER_EVENT_TIME": 1}
    # Not dispatched (no second strategy_dispatch_unavailable), closed in the Store.
    assert _reasons(store) == ["strategy_dispatch_unavailable", "out_of_order_event_time"]
    # The last admitted tick still decides qualification; the watermark did not move.
    assert feed.trade_qualification().last_received_at_utc == first.last_received_at_utc
    assert (feed._max_event_timestamp, feed._last_ingest_monotonic_ns) == watermark_state
    _feed_ticks(feed, store, clock, _event(3, 11))
    _feed_ticks(feed, store, clock, _event(4, 70))
    ((bar, _deliver),) = bars
    assert bar.volume == 6.0  # ticks 1 and 3; the dropped tick's size is lost
    assert "ORDERING_VOLUME_GAP" in bar.quality_flags
    assert "OUT_OF_ORDER_EVENT_TIME" not in bar.quality_flags


def test_backwards_duplicate_without_volume_leaves_the_bar_complete(feed_with_bars):
    feed, store, clock, bars = feed_with_bars
    _feed_ticks(feed, store, clock, _event(1, 10), _event(2, 11))
    _feed_ticks(feed, store, clock, _event(3, 10, latency=1.5, delta_volume=0.0))
    assert _statuses(feed) == [feed.LIVE]
    _feed_ticks(feed, store, clock, _event(4, 70))
    ((bar, deliver),) = bars
    assert (bar.complete, bar.quality_flags, bar.volume, deliver) == (True, (), 6.0, True)


def test_backwards_tick_for_a_published_bar_is_dropped(feed_with_bars):
    feed, store, clock, bars = feed_with_bars
    _feed_ticks(feed, store, clock, _event(1, 10))
    _feed_ticks(feed, store, clock, _event(2, 70))  # publishes minute 0
    _feed_ticks(feed, store, clock, _event(3, 30, latency=41.0, price=1999.0))
    assert _statuses(feed) == [feed.LIVE]  # was DELAYED (LATE_AFTER_WATERMARK)
    assert feed.tick_ingest_error_counts() == {"OUT_OF_ORDER_EVENT_TIME": 1}
    assert all(bar.close != 1999.0 for bar, _ in bars)


def test_sustained_backwards_ticks_degrade_after_the_limit(feed_with_bars):
    feed, store, clock, _bars = feed_with_bars
    _feed_ticks(feed, store, clock, _event(1, 10))
    _feed_ticks(feed, store, clock, _event(2, 9, latency=1.2), _event(3, 8, latency=2.3))
    assert _statuses(feed) == [feed.LIVE]
    assert feed.tick_ingest_error_counts() == {"OUT_OF_ORDER_EVENT_TIME": 2}
    _feed_ticks(feed, store, clock, _event(4, 7, latency=3.4))  # the third in a row
    assert _statuses(feed) == [feed.DELAYED]
    assert "FEED_NOT_LIVE" in feed.trade_qualification().reasons
    _feed_ticks(feed, store, clock, _event(5, 6, latency=4.5))
    assert feed._continuity_degraded is True
    _feed_ticks(feed, store, clock, _event(6, 11))  # time moves forward again
    assert _statuses(feed) == [feed.LIVE]
    _assert_live_and_tradable(feed)


def test_forward_ticks_reset_the_backwards_run(feed_with_bars):
    feed, store, clock, _bars = feed_with_bars
    _feed_ticks(feed, store, clock, _event(1, 10, latency=1.1))
    for sequence, forward in enumerate([11, 12, 13], 1):
        # One tick behind the last one, then one ahead of it: never two in a row.
        _feed_ticks(feed, store, clock, _event(2 * sequence, forward - 1.5, latency=2.1))
        _feed_ticks(feed, store, clock, _event(2 * sequence + 1, forward, latency=1.1))
    assert _statuses(feed) == [feed.LIVE]
    assert feed.tick_ingest_error_counts() == {"OUT_OF_ORDER_EVENT_TIME": 3}


def test_regression_limit_one_restores_the_old_handling(feed_with_bars):
    feed, store, clock, _bars = feed_with_bars
    feed._event_time_regression_limit = 1
    _feed_ticks(feed, store, clock, _event(1, 10))
    _feed_ticks(feed, store, clock, _event(2, 8, latency=4.0))
    assert _statuses(feed) == [feed.LIVE, feed.DELAYED]
    assert feed.tick_ingest_error_counts() == {}


@pytest.mark.parametrize("limit", [0, -1, True, 2.0, "3", None])
def test_invalid_regression_limit_is_refused(limit):
    with pytest.raises(ValueError, match="event_time_regression_limit"):
        BtApiFeed(dataname="SA609", store=None, event_time_regression_limit=limit)
