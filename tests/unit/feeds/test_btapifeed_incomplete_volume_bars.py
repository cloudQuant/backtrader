"""Iteration 62 decision 2 (user decision 2026-11-06): volume-incomplete bars.

A closed bar whose only defects are volume accounting (``VOLUME_INCOMPLETE``,
``VOLUME_BASELINE``, ``VOLUME_DISCONTINUITY``, ``ORDERING_VOLUME_GAP``) enters
the strategy's data lines by default (``incomplete_volume_bars="lines"``) or
only reaches ``notify_bar`` (``"notify_only"``, the earlier behaviour). Either
way its BarEvent keeps ``complete=False``, ``volume_complete=False`` and the
flags, and ``BtApiFeed.line_bar_quality()`` reports them for the line bar.

A healthy baseline tick (first tick after subscribe, reconnect or a trading
day change, or a volume reset) no longer makes an ordinary feed skip its
partially observed bucket: the bucket is built and marked ``VOLUME_BASELINE``.
The live bar cohort keeps its cold-start skip. Bars with any other defect
stay out of the lines as before.

Evidence level: UNIT/FAKE (in-process fake Store, injected monotonic clock).
"""

from __future__ import annotations

import pytest

pytest.importorskip("bt_api_py.market_tick_contracts")

import backtrader as bt  # noqa: E402
from backtrader.feeds.btapifeed import BtApiFeed, FeedLineBarQuality  # noqa: E402
from backtrader.feeds.market_tick_adapter import ingest_market_tick_event  # noqa: E402
from tests.unit.feeds.test_btapifeed_trade_qualification import (  # noqa: E402
    T0,
    _Clock,
    _event,
    _feed_ticks,
    _receipt_ns,
    _statuses,
    _Store,
)

OKX = dict(cumulative_volume=None)
JUMP = dict(
    OKX,
    continuity_status="continuous",
    volume_complete=False,
    volume_quality="discontinuous",
    delta_volume=4.0,
)
# CTP after D62-38: the first tick of a scope is a continuous volume baseline.
CTP_BASELINE = dict(
    continuity_status="continuous",
    volume_complete=False,
    volume_quality="BASELINE",
    delta_volume=0.0,
    cumulative_volume=1000.0,
)


def _continuous(cumulative):
    return dict(cumulative_volume=cumulative, delta_volume=3.0)


def _feed(mode=None, **params):
    store = _Store()
    clock = _Clock(_receipt_ns(0))
    if mode is not None:
        params["incomplete_volume_bars"] = mode
    feed = BtApiFeed(
        dataname="SA609",
        store=store,
        timeframe=bt.TimeFrame.Minutes,
        compression=1,
        price_tick=1.0,
        backfill_start=False,
        clock=clock,
        qcheck=0.0,
        **params,
    )
    feed._start()
    bars = []
    enqueue = feed._enqueue_bar_event

    def record(bar_event, bar_datetime, *, deliver_lines=True, bar_source=None):
        bars.append((bar_event, deliver_lines))
        return enqueue(bar_event, bar_datetime, deliver_lines=deliver_lines, bar_source=bar_source)

    feed._enqueue_bar_event = record
    return feed, store, clock, bars


@pytest.fixture
def lines_feed():
    harness = _feed()
    yield harness
    harness[0].stop()


@pytest.fixture
def notify_only_feed():
    harness = _feed("notify_only")
    yield harness
    harness[0].stop()


MINUTE0 = T0.replace(tzinfo=None)


def _line_time(feed):
    return feed.datetime.datetime(0)


# -- volume-incomplete bars ---------------------------------------------------


def test_jump_row_bar_enters_the_lines_by_default(lines_feed):
    feed, store, clock, bars = lines_feed
    _feed_ticks(feed, store, clock, _event(8, 10, **OKX))
    _feed_ticks(feed, store, clock, _event(9, 11, price=1502.0, **JUMP))
    assert _feed_ticks(feed, store, clock, _event(10, 70, price=1503.0, **OKX)) is True
    ((bar, deliver),) = bars
    assert deliver is True
    assert (bar.complete, bar.volume_complete, bar.quality_flags) == (
        False,
        False,
        ("VOLUME_INCOMPLETE",),
    )
    assert (_line_time(feed), feed.close[0], feed.volume[0]) == (MINUTE0, 1502.0, 7.0)
    assert feed.line_bar_quality() == FeedLineBarQuality(
        complete=False,
        volume_complete=False,
        quality_flags=("VOLUME_INCOMPLETE",),
        source="local_aggregation_volume_incomplete",
    )
    with pytest.raises(ValueError) as info:
        feed.valuation_mark()
    assert info.value.code == "MARK_SOURCE_UNTRUSTED"


def test_notify_only_keeps_volume_incomplete_bars_off_the_lines(notify_only_feed):
    feed, store, clock, bars = notify_only_feed
    _feed_ticks(feed, store, clock, _event(8, 10, **OKX))
    _feed_ticks(feed, store, clock, _event(9, 11, price=1502.0, **JUMP))
    assert _feed_ticks(feed, store, clock, _event(10, 70, **OKX)) is None
    ((bar, deliver),) = bars
    assert (bar.complete, bar.quality_flags, deliver) == (False, ("VOLUME_INCOMPLETE",), False)
    assert len(feed) == 0
    assert feed.line_bar_quality() is None


def test_complete_bars_report_their_quality(lines_feed):
    feed, store, clock, _bars = lines_feed
    _feed_ticks(feed, store, clock, _event(8, 10, **OKX), _event(9, 11, **OKX))
    assert _feed_ticks(feed, store, clock, _event(10, 70, **OKX)) is True
    assert feed.line_bar_quality() == FeedLineBarQuality(
        complete=True, volume_complete=True, quality_flags=(), source="local_aggregation"
    )


# -- baseline buckets -----------------------------------------------------------


def _baseline_then_continuous(feed, store, clock):
    _feed_ticks(feed, store, clock, _event(1, 10, **CTP_BASELINE))
    _feed_ticks(feed, store, clock, _event(2, 11, **_continuous(1003.0)))
    _feed_ticks(feed, store, clock, _event(3, 12, **_continuous(1006.0)))
    return _feed_ticks(feed, store, clock, _event(4, 70, **_continuous(1009.0)))


def test_baseline_bucket_is_built_marked_and_on_the_lines(lines_feed):
    feed, store, clock, bars = lines_feed
    assert _baseline_then_continuous(feed, store, clock) is True
    assert _statuses(feed) == [feed.LIVE]
    ((bar, deliver),) = bars  # was skipped entirely (cold start)
    assert (bar.complete, bar.quality_flags, bar.volume, deliver) == (
        False,
        ("VOLUME_BASELINE",),
        6.0,
        True,
    )
    assert feed.line_bar_quality().quality_flags == ("VOLUME_BASELINE",)
    assert feed._initial_volume_baseline_start is None  # no cold-start skip


def test_baseline_bucket_with_notify_only(notify_only_feed):
    feed, store, clock, bars = notify_only_feed
    assert _baseline_then_continuous(feed, store, clock) is None
    ((bar, deliver),) = bars
    assert (bar.quality_flags, bar.volume, deliver) == (("VOLUME_BASELINE",), 6.0, False)


def test_volume_reset_bar_keeps_both_continuous_ticks(lines_feed):
    feed, store, clock, bars = lines_feed
    reset = dict(CTP_BASELINE, cumulative_volume=10.0, quality_flags=("VOLUME_DISCONTINUITY",))
    _feed_ticks(feed, store, clock, _event(1, 10, **_continuous(100.0)))
    _feed_ticks(feed, store, clock, _event(2, 11, **reset))
    _feed_ticks(feed, store, clock, _event(3, 12, **_continuous(13.0)))
    _feed_ticks(feed, store, clock, _event(4, 70, **_continuous(16.0)))
    assert _statuses(feed) == [feed.LIVE]
    ((bar, deliver),) = bars
    assert set(bar.quality_flags) == {"VOLUME_BASELINE", "VOLUME_DISCONTINUITY"}
    assert (bar.volume, bar.trade_count, deliver) == (6.0, 2, True)


def test_dropped_backwards_tick_bar_enters_the_lines(lines_feed):
    feed, store, clock, bars = lines_feed
    _feed_ticks(feed, store, clock, _event(1, 10))
    _feed_ticks(feed, store, clock, _event(2, 8, latency=4.0))  # dropped, volume lost
    _feed_ticks(feed, store, clock, _event(3, 70))
    ((bar, deliver),) = bars
    assert (bar.quality_flags, deliver) == (("ORDERING_VOLUME_GAP",), True)


# -- other defects stay out of the lines ---------------------------------------


def test_volume_flag_with_another_defect_stays_off_the_lines(lines_feed):
    feed, store, clock, bars = lines_feed
    _feed_ticks(feed, store, clock, _event(8, 10, **OKX))
    _feed_ticks(feed, store, clock, _event(9, 11, price=1500.5, **JUMP))  # off the grid
    _feed_ticks(feed, store, clock, _event(10, 70, **OKX))
    ((bar, deliver),) = bars
    assert {"VOLUME_INCOMPLETE", "LAST_PRICE_OFF_GRID"} <= set(bar.quality_flags)
    assert deliver is False


def test_forced_invalidation_stays_off_the_lines(lines_feed):
    feed, store, clock, bars = lines_feed
    _feed_ticks(feed, store, clock, _event(8, 10, **OKX))
    _feed_ticks(feed, store, clock, _event(9, 11, price=1502.0, **JUMP))
    feed._flush_ready_bars(reason="test", force_invalid=True)
    ((bar, deliver),) = bars
    assert "FORCED_INVALIDATION" in bar.quality_flags
    assert deliver is False


def test_late_bar_stays_off_the_lines(lines_feed):
    feed, store, clock, bars = lines_feed
    _feed_ticks(feed, store, clock, _event(1, 10, latency=0.1))
    _feed_ticks(feed, store, clock, _event(2, 59.9, latency=1.0))
    _feed_ticks(feed, store, clock, _event(3, 70))
    ((bar, deliver),) = bars
    assert "LATE_AFTER_WATERMARK" in bar.quality_flags
    assert deliver is False


# -- parameters and the cohort ----------------------------------------------------


@pytest.mark.parametrize("mode", ["both", "", "LINES", None, True, 1])
def test_invalid_mode_is_refused(mode):
    with pytest.raises(ValueError, match="incomplete_volume_bars"):
        BtApiFeed(dataname="SA609", store=None, incomplete_volume_bars=mode)


def test_history_bar_quality_is_unknown_volume():
    history = {
        "datetime": MINUTE0,
        "open": 1.0,
        "high": 1.0,
        "low": 1.0,
        "close": 1.0,
        "volume": 1.0,
        "openinterest": 0.0,
        "bar_final": True,
    }
    feed = BtApiFeed(
        dataname="SA609",
        store=None,
        timeframe=bt.TimeFrame.Minutes,
        compression=1,
        historical_bars=[history],
        backfill_start=False,
    )
    feed._start()
    try:
        assert feed.line_bar_quality() is None
        assert feed.load() is True
        assert feed.line_bar_quality() == FeedLineBarQuality(
            complete=True, volume_complete=None, quality_flags=(), source="provider_bar"
        )
    finally:
        feed.stop()


@pytest.mark.parametrize("cohort", [False, True], ids=["ordinary", "cohort"])
def test_baseline_marks_the_bucket_or_records_the_cohort_cold_start(cohort):
    tick = ingest_market_tick_event(_event(1, 10, **CTP_BASELINE), event_time_max_age=2.0).tick
    feed = BtApiFeed(
        dataname="SA609",
        store=None,
        timeframe=bt.TimeFrame.Minutes,
        compression=1,
        price_tick=1.0,
        clock=_Clock(_receipt_ns(10)),
    )
    if cohort:
        feed._live_bar_cohort = object()  # only the cohort switch of this method
    assert feed._record_initial_volume_baseline(tick) is True
    if cohort:
        assert feed._initial_volume_baseline_start == MINUTE0
        assert not feed._bar_quality_overrides
    else:
        assert feed._initial_volume_baseline_start is None
        assert feed._bar_quality_overrides[MINUTE0] == {"VOLUME_BASELINE"}
