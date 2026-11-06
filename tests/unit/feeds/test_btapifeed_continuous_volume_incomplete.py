"""Iteration 62 (user decision 2026-11-06): incomplete volume on a continuous tick.

An OKX trade-id jump on an uninterrupted connection arrives as a typed SDK
tick with ``continuity_status="continuous"`` and ``volume_complete=False``
(``volume_quality="discontinuous"``); it still reports its own size. Such a
tick is a normal tick for prices, feed health and trade qualification. The
incomplete volume is a bar-only flag: the tick enters its bar with its own
size and that bar carries ``VOLUME_INCOMPLETE`` (incomplete, as before).

Real gaps are unchanged: any other continuity with incomplete volume still
blocks the tick and degrades the feed, and CTP tick shapes (baseline first
tick, reset, continuous) behave exactly as before.

Ticks are built from the public Base/SDK dataclasses only. Evidence level:
UNIT/FAKE (in-process fake Store, injected monotonic clock).
"""

from __future__ import annotations

import pytest

pytest.importorskip("bt_api_py.market_tick_contracts")

import backtrader as bt  # noqa: E402
from backtrader.feeds.btapifeed import BtApiFeed  # noqa: E402
from backtrader.feeds.market_tick_adapter import ingest_market_tick_event  # noqa: E402
from tests.unit.feeds.test_btapifeed_trade_qualification import (  # noqa: E402
    _Clock,
    _event,
    _feed_ticks,
    _receipt_ns,
    _statuses,
    _Store,
)

# OKX trade rows carry a per-trade size and no cumulative volume.
OKX = dict(cumulative_volume=None)
JUMP = dict(
    OKX,
    continuity_status="continuous",
    volume_complete=False,
    volume_quality="discontinuous",
    delta_volume=4.0,
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


def _prepared(event, receipt_second):
    tick = ingest_market_tick_event(event, event_time_max_age=2.0).tick
    feed = BtApiFeed(
        dataname="SA609",
        store=None,
        timeframe=bt.TimeFrame.Minutes,
        compression=1,
        price_tick=1.0,
        clock=_Clock(_receipt_ns(receipt_second)),
    )
    feed._prepare_tick(tick)
    return tick, feed


# -- continuous tick with incomplete volume (OKX trade-id jump row) ------------


def test_continuous_incomplete_volume_tick_is_tradable_and_healthy():
    tick, _feed = _prepared(_event(9, 11, **JUMP), 11)
    assert tick.quality_flags == ("VOLUME_INCOMPLETE",)
    assert tick.quality == "GOOD"
    assert tick.data_quality == "GOOD"
    assert tick.execution_eligible is True
    assert tick.bar_eligible is True


def test_continuous_jump_row_keeps_feed_live_and_flags_only_its_bar(feed_with_bars):
    feed, store, clock, bars = feed_with_bars
    _feed_ticks(feed, store, clock, _event(8, 10, **OKX))
    assert _statuses(feed) == [feed.LIVE]
    _feed_ticks(feed, store, clock, _event(9, 11, price=1502.0, **JUMP))
    assert _statuses(feed) == []  # no DELAYED
    assert feed._continuity_degraded is False
    verdict = feed.trade_qualification()
    assert verdict.live is True
    assert "FEED_NOT_LIVE" not in verdict.reasons
    assert verdict.ok is True
    _feed_ticks(feed, store, clock, _event(10, 12, price=1501.0, **OKX))
    assert feed.trade_qualification().ok is True
    # Minute 1 closes minute 0, which contains the jump row.
    _feed_ticks(feed, store, clock, _event(11, 70, **OKX))
    assert _statuses(feed) == []
    assert len(bars) == 1
    bar, deliver_lines = bars[0]
    assert "VOLUME_INCOMPLETE" in bar.quality_flags
    assert bar.complete is False
    assert bar.quality == "INVALID"
    assert deliver_lines is False  # incomplete bars stay out of lines, as before
    # The jump row is a normal tick for prices and adds its own size.
    assert (bar.open, bar.high, bar.low, bar.close) == (1500.0, 1502.0, 1500.0, 1501.0)
    assert bar.volume == 3.0 + 4.0 + 3.0
    assert bar.trade_count == 3


def test_jump_row_opening_a_bucket_marks_that_bar_volume_incomplete(feed_with_bars):
    feed, store, clock, bars = feed_with_bars
    _feed_ticks(feed, store, clock, _event(8, 10, **OKX))
    _feed_ticks(feed, store, clock, _event(9, 61, **JUMP))  # first tick of minute 1
    _feed_ticks(feed, store, clock, _event(10, 62, **OKX))
    _feed_ticks(feed, store, clock, _event(11, 121, **OKX))  # closes minute 1
    assert _statuses(feed) == [feed.LIVE]
    assert [bar.complete for bar, _ in bars] == [True, False]
    minute1 = bars[1][0]
    assert minute1.quality_flags == ("VOLUME_INCOMPLETE",)
    assert minute1.volume_complete is False
    assert minute1.volume == 4.0 + 3.0


def test_continuous_jump_row_with_cumulative_volume_is_not_a_cold_start(feed_with_bars):
    """A source that also reports cumulative volume: the bucket is still built."""
    feed, store, clock, bars = feed_with_bars
    jump = dict(JUMP, cumulative_volume=12349.0)
    _feed_ticks(feed, store, clock, _event(8, 10, cumulative_volume=12345.0))
    _feed_ticks(feed, store, clock, _event(9, 11, **jump))
    _feed_ticks(feed, store, clock, _event(10, 12, cumulative_volume=12352.0))
    assert feed._initial_volume_baseline_start is None
    _feed_ticks(feed, store, clock, _event(11, 70, cumulative_volume=12355.0))
    bar = bars[0][0]
    assert bar.quality_flags == ("VOLUME_INCOMPLETE",)
    assert (bar.volume, bar.trade_count) == (3.0 + 4.0 + 3.0, 3)


def test_continuous_jump_row_with_another_data_defect_still_blocks(feed_with_bars):
    """Only incomplete volume is bar-only; the bar keeps both defects."""
    feed, store, clock, bars = feed_with_bars
    _feed_ticks(feed, store, clock, _event(8, 10, **OKX))
    _feed_ticks(feed, store, clock, _event(9, 11, price=1500.5, **JUMP))  # off the grid
    assert _statuses(feed) == [feed.LIVE, feed.DELAYED]
    assert "FEED_NOT_LIVE" in feed.trade_qualification().reasons
    _feed_ticks(feed, store, clock, _event(10, 70, **OKX))
    bar = bars[0][0]
    assert {"VOLUME_INCOMPLETE", "LAST_PRICE_OFF_GRID"} <= set(bar.quality_flags)
    assert bar.complete is False
    assert bar.volume == 3.0  # the rejected tick never entered the bar


def test_tick_timeframe_line_takes_the_jump_row():
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
        assert _feed_ticks(feed, store, clock, _event(8, 10, **OKX)) is True
        assert _feed_ticks(feed, store, clock, _event(9, 11, price=1502.0, **JUMP)) is True
        assert (feed.close[0], feed.volume[0]) == (1502.0, 4.0)
        assert feed._valuation_bar[3] == "market_tick"
        assert _statuses(feed) == [feed.LIVE]
        assert feed.trade_qualification().ok is True
    finally:
        feed.stop()


# -- real gaps are unchanged ---------------------------------------------------


@pytest.mark.parametrize("continuity", ["gap", "recovered", "snapshot", "ok", "unknown"])
def test_incomplete_volume_without_continuous_continuity_still_blocks(continuity):
    event = _event(9, 11, **JUMP)
    tick = ingest_market_tick_event(event, event_time_max_age=2.0).tick
    tick.continuity_status = continuity
    feed = BtApiFeed(
        dataname="SA609",
        store=None,
        timeframe=bt.TimeFrame.Minutes,
        compression=1,
        price_tick=1.0,
        clock=_Clock(_receipt_ns(11)),
    )
    feed._prepare_tick(tick)
    assert "VOLUME_INCOMPLETE" in tick.quality_flags
    assert tick.quality == "INVALID"
    assert tick.data_quality == "INVALID"
    assert tick.execution_eligible is False
    assert tick.bar_eligible is False
    assert feed._handle_event_health(tick) is True  # unhealthy


def test_gap_tick_with_incomplete_volume_degrades_as_before(feed_with_bars):
    feed, store, clock, bars = feed_with_bars
    gap = dict(JUMP, continuity_status="gap")
    _feed_ticks(feed, store, clock, _event(8, 10, **OKX))
    _feed_ticks(feed, store, clock, _event(9, 11, price=1502.0, **gap))
    assert _statuses(feed) == [feed.LIVE, feed.DELAYED]
    assert feed._continuity_degraded is True
    verdict = feed.trade_qualification()
    assert verdict.live is False
    assert "FEED_NOT_LIVE" in verdict.reasons
    _feed_ticks(feed, store, clock, _event(10, 12, price=1501.0, **OKX))
    assert _statuses(feed) == [feed.LIVE]
    _feed_ticks(feed, store, clock, _event(11, 70, **OKX))
    bar = bars[0][0]
    assert "VOLUME_INCOMPLETE" in bar.quality_flags
    assert bar.complete is False
    assert (bar.high, bar.volume, bar.trade_count) == (1501.0, 6.0, 2)  # gap row excluded


# -- CTP shapes and normal ticks (unchanged) -------------------------------------

# The CTP ticker emits ``continuous`` only for complete CONTINUOUS volume; its
# first tick after subscribe and any reset carry delta 0, incomplete, ``gap``.
CTP_BASELINE = dict(
    delta_volume=0.0,
    cumulative_volume=1000.0,
    volume_complete=False,
    volume_quality="baseline",
    continuity_status="gap",
)
CTP_RESET = dict(CTP_BASELINE, volume_quality="discontinuous")
CTP_CONTINUOUS = dict(
    delta_volume=3.0,
    cumulative_volume=1003.0,
    volume_complete=True,
    volume_quality="continuous",
    continuity_status="continuous",
)


@pytest.mark.parametrize("shape", [CTP_BASELINE, CTP_RESET], ids=["baseline", "reset"])
def test_ctp_incomplete_shapes_keep_their_flags(shape):
    tick, feed = _prepared(_event(1, 10, **shape), 10)
    assert tick.quality_flags == ("VOLUME_BASELINE",)
    assert "VOLUME_INCOMPLETE" not in tick.quality_flags
    assert tick.bar_eligible is False
    assert feed._handle_event_health(tick) is True  # continuity gap degrades


def test_ctp_baseline_first_tick_then_continuous_ticks(feed_with_bars):
    feed, store, clock, bars = feed_with_bars
    _feed_ticks(feed, store, clock, _event(1, 10, **CTP_BASELINE))
    assert _statuses(feed) == [feed.DELAYED]
    assert "FEED_NOT_LIVE" in feed.trade_qualification().reasons
    _feed_ticks(feed, store, clock, _event(2, 11, **CTP_CONTINUOUS))
    assert _statuses(feed) == [feed.LIVE]
    assert feed.trade_qualification().ok is True
    _feed_ticks(feed, store, clock, _event(3, 12, **dict(CTP_CONTINUOUS, cumulative_volume=1006.0)))
    _feed_ticks(feed, store, clock, _event(4, 70, **dict(CTP_CONTINUOUS, cumulative_volume=1009.0)))
    _feed_ticks(
        feed, store, clock, _event(5, 130, **dict(CTP_CONTINUOUS, cumulative_volume=1012.0))
    )
    assert _statuses(feed) == []
    assert all("VOLUME_INCOMPLETE" not in (bar.quality_flags or ()) for bar, _ in bars)
    assert [(bar.complete, bar.volume, deliver) for bar, deliver in bars] == [
        (True, 6.0, True),
        (True, 3.0, True),
    ]


def test_normal_complete_ticks_are_unchanged(feed_with_bars):
    feed, store, clock, bars = feed_with_bars
    tick, _feed = _prepared(_event(8, 10, **OKX), 10)
    assert (tick.quality, tick.quality_flags, tick.execution_eligible, tick.bar_eligible) == (
        "GOOD",
        (),
        True,
        True,
    )
    _feed_ticks(feed, store, clock, _event(8, 10, **OKX), _event(9, 11, price=1501.0, **OKX))
    assert _statuses(feed) == [feed.LIVE]
    assert feed.trade_qualification().ok is True
    assert _feed_ticks(feed, store, clock, _event(10, 70, **OKX)) is True
    bar, deliver_lines = bars[0]
    assert bar.quality_flags == ()
    assert (bar.complete, bar.quality, bar.volume, deliver_lines) == (True, "GOOD", 6.0, True)
    assert feed.close[0] == 1501.0
