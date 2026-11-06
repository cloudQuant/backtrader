"""Iteration 62 acceptance finding (SimNow night 2026-11-07): a DELAYED feed says why.

A contract configured with the wrong ``price_tick`` (gold at 1.0 instead of
0.02) kept a live feed DELAYED for minutes with nothing in the log: every price
was off the tick grid, so no tick was executable. The LIVE -> DELAYED
transition now logs its cause, the tick's quality flags and the configured
price tick; repeats of a flapping feed are summarized by the throttled logger.
Evidence level: UNIT/FAKE (in-process fake Store, injected clock).
"""

from __future__ import annotations

import logging

import pytest

pytest.importorskip("bt_api_py.market_tick_contracts")

import backtrader as bt  # noqa: E402
from backtrader.feeds import btapifeed as btapifeed_module  # noqa: E402
from backtrader.feeds.btapifeed import BtApiFeed  # noqa: E402
from backtrader.utils import log_message  # noqa: E402
from tests.unit.feeds.test_btapifeed_trade_qualification import (  # noqa: E402
    _Clock,
    _event,
    _feed_ticks,
    _receipt_ns,
    _statuses,
    _Store,
)

GOLD = {"price": 950.32, "bid_price": 950.30, "ask_price": 950.34}


@pytest.fixture
def delayed_lines(monkeypatch):
    records = []

    class _ListHandler(logging.Handler):
        def emit(self, record):
            records.append(record.getMessage())

    handler = _ListHandler(level=logging.WARNING)
    logger = btapifeed_module.logger
    monkeypatch.setattr(log_message, "_throttle_state", {})
    monkeypatch.setattr(logger, "level", logging.WARNING)
    logger.addHandler(handler)
    yield lambda: [message for message in records if " DELAYED (" in message]
    logger.removeHandler(handler)


def _started(price_tick):
    store = _Store()
    clock = _Clock(_receipt_ns(0))
    feed = BtApiFeed(
        dataname="au2612",
        store=store,
        timeframe=bt.TimeFrame.Minutes,
        compression=1,
        price_tick=price_tick,
        backfill_start=False,
        clock=clock,
        qcheck=0.0,
    )
    feed._start()
    return feed, store, clock


def test_off_grid_prices_log_why_the_feed_stays_delayed(delayed_lines):
    feed, store, clock = _started(price_tick=1.0)
    try:
        _feed_ticks(feed, store, clock, *(_event(seq, 10 + seq, **GOLD) for seq in range(1, 4)))
        assert feed.LIVE not in _statuses(feed)
        lines = delayed_lines()
        assert len(lines) == 1
        assert "au2612 DELAYED (cause=data_not_executable" in lines[0]
        assert "LAST_PRICE_OFF_GRID" in lines[0]
        assert "price_tick=1.0" in lines[0]
    finally:
        feed.stop()


def test_the_correct_tick_keeps_the_feed_live_without_a_delayed_line(delayed_lines):
    feed, store, clock = _started(price_tick=0.02)
    try:
        _feed_ticks(feed, store, clock, _event(1, 10, **GOLD))
        assert _statuses(feed) == [feed.LIVE]
        assert delayed_lines() == []
    finally:
        feed.stop()


def test_a_flapping_feed_logs_its_first_transition_only(delayed_lines):
    feed, store, clock = _started(price_tick=0.02)
    off_grid = dict(GOLD, price=950.33)
    try:
        for second in range(10, 16, 2):
            _feed_ticks(feed, store, clock, _event(second, second, **GOLD))
            _feed_ticks(feed, store, clock, _event(second + 1, second + 1, **off_grid))
        assert _statuses(feed).count(feed.DELAYED) == 3
        lines = delayed_lines()
        assert len(lines) == 1
        assert "LAST_PRICE_OFF_GRID" in lines[0]
    finally:
        feed.stop()
