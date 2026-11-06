"""D62-38 provider tick shapes through BtApiFeed (iteration 62, 2026-11-06).

One test per row of the provider change (bt_api_ctp 5843b66, bt_api_binance
2034334), built with the neutral payload fields those providers now emit:

* first tick after subscribe (readiness tick published): continuous baseline;
* first tick after a reconnect or subscription-epoch change: continuous
  baseline of the new scope; the scope change stays a diagnostic flag on the
  tick and still resets the bar state, and older-scope ticks after it are
  refused (they never mix into the new scope's bars);
* trading-day switch: continuous baseline with the new trading date;
* cumulative-volume decrease: continuous, ``VOLUME_DISCONTINUITY``;
* limit-locked book: continuous, ``LIMIT_LOCKED_UP/DOWN`` + ``ZERO_DEPTH``,
  the empty side's price ``None`` and size 0;
* ``LOCKED_BOOK`` / ``ZERO_DEPTH`` under their own names;
* tick after a provider queue drop: ``gap`` with incomplete volume (degrades);
* Binance first tick and aggTrade id jump: continuous (incomplete on a jump).

Evidence level: UNIT/FAKE (public Base/SDK dataclasses, fake Store, injected
clock). The provider commits themselves are not imported or run here.
"""

from __future__ import annotations

import pytest

pytest.importorskip("bt_api_py.market_tick_contracts")

import backtrader as bt  # noqa: E402
from backtrader.feeds.btapifeed import BtApiFeed  # noqa: E402
from tests.unit.feeds.test_btapifeed_d62_38_feed_health import _event_scope  # noqa: E402
from tests.unit.feeds.test_btapifeed_trade_qualification import (  # noqa: E402
    _Clock,
    _event,
    _feed_ticks,
    _receipt_ns,
    _statuses,
    _Store,
)

CTP_BASELINE = dict(
    continuity_status="continuous",
    volume_complete=False,
    volume_quality="baseline",
    delta_volume=0.0,
    cumulative_volume=1000.0,
)
CTP_VOLUME_DECREASE = dict(
    CTP_BASELINE,
    volume_quality="discontinuous",
    cumulative_volume=10.0,
    quality_flags=("VOLUME_DISCONTINUITY",),
)
CTP_LIMIT_UP = dict(
    last_price=1600.0,
    bid_price=1600.0,
    bid_size=50.0,
    ask_price=None,  # DBL_MAX projected as absent
    ask_size=0.0,
    upper_limit=1600.0,
    lower_limit=1400.0,
    quality_flags=("LIMIT_LOCKED_UP", "ZERO_DEPTH"),
)
CTP_LIMIT_DOWN = dict(
    last_price=1400.0,
    bid_price=None,
    bid_size=0.0,
    ask_price=1400.0,
    ask_size=40.0,
    upper_limit=1600.0,
    lower_limit=1400.0,
    quality_flags=("LIMIT_LOCKED_DOWN", "ZERO_DEPTH"),
)
QUEUE_DROP = dict(
    continuity_status="gap",
    volume_complete=False,
    volume_quality="discontinuous",
    delta_volume=3.0,
)
BINANCE_FIRST = dict(
    continuity_status="continuous",
    volume_complete=False,
    volume_quality="baseline",
    delta_volume=0.0,
    cumulative_volume=None,
)
BINANCE_JUMP = dict(
    continuity_status="continuous",
    volume_complete=False,
    volume_quality="discontinuous",
    delta_volume=0.7,
    cumulative_volume=None,
)


@pytest.fixture
def harness():
    store = _Store()
    clock = _Clock(_receipt_ns(0))
    feed = BtApiFeed(
        dataname="SA609",
        store=store,
        timeframe=bt.TimeFrame.Minutes,
        compression=1,
        price_tick=0.1,
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


def _tradable(feed):
    verdict = feed.trade_qualification()
    return verdict.live and verdict.ok and not feed._continuity_degraded


def _limit(shape):
    values = dict(shape)
    return values.pop("last_price"), values


def test_row_first_tick_after_subscribe(harness):
    feed, store, clock, _bars = harness
    _feed_ticks(feed, store, clock, _event(1, 10, **CTP_BASELINE))
    assert _statuses(feed) == [feed.LIVE]
    assert _tradable(feed)


@pytest.mark.parametrize(
    "scope, flag",
    [
        (dict(generation=2), "CONNECTION_GENERATION_CHANGED"),
        (dict(generation=1, epoch=2), "SUBSCRIPTION_EPOCH_CHANGED"),
    ],
    ids=["reconnect", "subscription_epoch"],
)
def test_row_first_tick_of_a_newer_scope(harness, scope, flag):
    feed, store, clock, bars = harness
    _feed_ticks(feed, store, clock, _event_scope(1, 10, generation=1))
    _feed_ticks(feed, store, clock, _event_scope(2, 65, generation=1))  # opens minute 1
    tick_holder = []
    dispatch = feed._dispatch_event
    feed._dispatch_event = lambda channel_type, priority, event_data: (
        tick_holder.append(event_data),
        dispatch(channel_type, priority, event_data),
    )[1]
    _feed_ticks(feed, store, clock, _event_scope(1, 66, **scope, **CTP_BASELINE))
    assert _statuses(feed) == [feed.LIVE]  # no DELAYED
    assert _tradable(feed)
    new_tick = tick_holder[-1]
    assert flag in new_tick.quality_flags  # still a diagnostic flag on the tick
    assert new_tick.data_quality == "GOOD"
    # The old scope's open minute was invalidated, never continued by the new scope.
    invalidated = [bar for bar, _ in bars if "FORCED_INVALIDATION" in bar.quality_flags]
    assert len(invalidated) == 1 and invalidated[0].volume == 3.0
    # An older-scope tick after the change is refused and degrades the feed.
    _feed_ticks(feed, store, clock, _event_scope(3, 67, generation=1, price=1999.0))
    assert _statuses(feed) == [feed.DELAYED]
    _feed_ticks(feed, store, clock, _event_scope(2, 125, **scope))
    _feed_ticks(feed, store, clock, _event_scope(3, 130, **scope))
    _feed_ticks(feed, store, clock, _event_scope(4, 190, **scope))
    assert _statuses(feed) == [feed.LIVE]
    assert all(bar.close != 1999.0 for bar, _ in bars)


def test_row_trading_day_switch(harness):
    feed, store, clock, _bars = harness
    _feed_ticks(feed, store, clock, _event(1, 10), _event(2, 11))
    switch = dict(CTP_BASELINE, trading_date="2026-11-03")
    _feed_ticks(feed, store, clock, _event(3, 12, **switch))
    assert _statuses(feed) == [feed.LIVE]
    assert _tradable(feed)


def test_row_cumulative_volume_decrease(harness):
    feed, store, clock, bars = harness
    _feed_ticks(feed, store, clock, _event(1, 10, cumulative_volume=100.0))
    _feed_ticks(feed, store, clock, _event(2, 11, **CTP_VOLUME_DECREASE))
    assert _statuses(feed) == [feed.LIVE]
    assert _tradable(feed)
    _feed_ticks(feed, store, clock, _event(3, 70, cumulative_volume=13.0))
    ((bar, deliver),) = bars
    assert "VOLUME_DISCONTINUITY" in bar.quality_flags and deliver is True


@pytest.mark.parametrize(
    "shape, side", [(CTP_LIMIT_UP, "UP"), (CTP_LIMIT_DOWN, "DOWN")], ids=["up", "down"]
)
def test_row_limit_locked_book(harness, shape, side):
    feed, store, clock, bars = harness
    price, values = _limit(shape)
    ticks = []
    dispatch = feed._dispatch_event
    feed._dispatch_event = lambda channel_type, priority, event_data: (
        ticks.append(event_data),
        dispatch(channel_type, priority, event_data),
    )[1]
    _feed_ticks(feed, store, clock, _event(1, 10, price=price, **values))
    _feed_ticks(feed, store, clock, _event(2, 11, price=price, **values))
    assert _statuses(feed) == [feed.LIVE]
    assert _tradable(feed)
    tick = ticks[0]
    assert {f"LIMIT_LOCKED_{side}", "ZERO_DEPTH"} <= set(tick.quality_flags)
    assert not {"ASK_PRICE_INVALID", "BID_PRICE_INVALID", "CROSSED_BOOK"} & set(tick.quality_flags)
    assert (tick.quality, tick.execution_eligible, tick.bar_eligible) == ("GOOD", True, True)
    _feed_ticks(feed, store, clock, _event(3, 70, price=price, **values))
    ((bar, deliver),) = [item for item in bars if item[0].bucket_start.second == 0][:1]
    assert (bar.complete, bar.quality_flags, deliver) == (True, (), True)
    assert f"LIMIT_LOCKED_{side}" in bar.quality_warnings


def test_row_limit_lock_without_the_snapshot_limit_stays_invalid(harness):
    """The provider flag alone is not enough: the quoting side must equal the limit."""
    feed, store, clock, _bars = harness
    price, values = _limit(dict(CTP_LIMIT_UP, upper_limit=1650.0))
    _feed_ticks(feed, store, clock, _event(1, 10))
    _feed_ticks(feed, store, clock, _event(2, 11, price=price, **values))
    assert _statuses(feed) == [feed.LIVE, feed.DELAYED]


@pytest.mark.parametrize(
    "values",
    [
        dict(quality_flags=("LOCKED_BOOK",), bid_price=1500.0, ask_price=1500.0),
        dict(quality_flags=("ZERO_DEPTH",), ask_size=0.0),
    ],
    ids=["locked_book", "zero_depth"],
)
def test_row_locked_book_and_zero_depth_are_warnings(harness, values):
    feed, store, clock, _bars = harness
    _feed_ticks(feed, store, clock, _event(1, 10, **values))
    assert _statuses(feed) == [feed.LIVE]
    assert _tradable(feed)


def test_row_tick_after_a_provider_queue_drop_degrades(harness):
    feed, store, clock, _bars = harness
    _feed_ticks(feed, store, clock, _event(1, 10))
    _feed_ticks(feed, store, clock, _event(2, 11, cumulative_volume=1003.0, **QUEUE_DROP))
    assert _statuses(feed) == [feed.LIVE, feed.DELAYED]
    assert not _tradable(feed)
    _feed_ticks(feed, store, clock, _event(3, 12, cumulative_volume=1006.0))
    assert _statuses(feed) == [feed.LIVE]


def test_row_binance_first_tick_and_trade_id_jump(harness):
    feed, store, clock, bars = harness
    _feed_ticks(feed, store, clock, _event(1, 10, **BINANCE_FIRST))
    assert _statuses(feed) == [feed.LIVE]
    assert _tradable(feed)
    _feed_ticks(feed, store, clock, _event(2, 70, cumulative_volume=None))
    _feed_ticks(feed, store, clock, _event(3, 71, price=1500.1, **BINANCE_JUMP))
    assert _statuses(feed) == []
    assert _tradable(feed)
    _feed_ticks(feed, store, clock, _event(4, 130, cumulative_volume=None))
    jump_bar, deliver = bars[-1]
    assert jump_bar.quality_flags == ("VOLUME_INCOMPLETE",)
    assert (jump_bar.volume, deliver) == (3.0 + 0.7, True)
    assert feed.volume[0] == pytest.approx(3.7)
