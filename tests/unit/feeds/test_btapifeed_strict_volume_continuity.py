"""Iteration 62, D62-38 decision 3 (user 2026-11-06): opt-in strict volume continuity.

By default volume-accounting defects are bar-only flags (the tick stays LIVE
and tradable). A strategy may opt in to ``strict_volume_continuity=True``
(``feed:`` section of its config.yaml), which restores the pre-D62-38 rule:
VOLUME_INCOMPLETE, VOLUME_DISCONTINUITY and a VOLUME_BASELINE tick block like
data defects. Evidence level: UNIT/FAKE (in-process fake Store, injected clock).
"""

from __future__ import annotations

import pytest

pytest.importorskip("bt_api_py.market_tick_contracts")

import backtrader as bt  # noqa: E402
from backtrader.feeds.btapifeed import BtApiFeed  # noqa: E402
from tests.unit.feeds.test_btapifeed_d62_38_feed_health import (  # noqa: E402
    BASELINE,
    BASELINE_WITH_SIZE,
    VOLUME_RESET,
)
from tests.unit.feeds.test_btapifeed_trade_qualification import (  # noqa: E402
    _Clock,
    _event,
    _feed_ticks,
    _receipt_ns,
    _statuses,
    _Store,
)


def _started(strict):
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
        strict_volume_continuity=strict,
    )
    feed._start()
    return feed, store, clock


@pytest.mark.parametrize(
    "shape", [BASELINE, BASELINE_WITH_SIZE], ids=["baseline_size0", "baseline_size_gt0"]
)
def test_strict_mode_blocks_a_volume_baseline_first_tick(shape):
    feed, store, clock = _started(strict=True)
    try:
        _feed_ticks(feed, store, clock, _event(1, 10, **shape))
        assert feed.LIVE not in _statuses(feed)
        assert feed.trade_qualification().ok is False
    finally:
        feed.stop()


def test_strict_mode_degrades_on_a_volume_discontinuity():
    feed, store, clock = _started(strict=True)
    try:
        _feed_ticks(feed, store, clock, _event(1, 10))
        assert _statuses(feed) == [feed.LIVE]
        _feed_ticks(feed, store, clock, _event(2, 11, cumulative_volume=10.0, **VOLUME_RESET))
        assert _statuses(feed) == [feed.DELAYED]
        assert feed.trade_qualification().ok is False
    finally:
        feed.stop()


@pytest.mark.parametrize("shape", [BASELINE, BASELINE_WITH_SIZE, VOLUME_RESET])
def test_default_mode_keeps_the_same_shapes_live(shape):
    feed, store, clock = _started(strict=False)
    try:
        _feed_ticks(feed, store, clock, _event(1, 10, **shape))
        assert feed.trade_qualification().ok is True
    finally:
        feed.stop()


def test_the_strict_switch_must_be_a_bool():
    with pytest.raises(ValueError, match="strict_volume_continuity"):
        BtApiFeed(dataname="SA609", store=None, strict_volume_continuity="yes")
