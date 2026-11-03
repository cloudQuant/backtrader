"""Iteration 60, acceptance report P1-6: published bars are never rewritten.

Provider bars are closed intervals identified by feed + open time. After a
bar is published to the line buffers, a late bar (earlier time), a duplicate
(same time and values, e.g. the history/live overlap) and a revision (same
time, different values) are all dropped and counted; nothing is rewritten.
"""

from __future__ import annotations

import collections
import datetime as dt

import pytest

pytest.importorskip("bt_api_py")

import backtrader as bt  # noqa: E402
from backtrader.feeds.btapifeed import BtApiFeed  # noqa: E402

T0 = dt.datetime(2026, 11, 3, 9, 0)


def _bar(minute, close=100.0, volume=1.0):
    return {
        "datetime": T0 + dt.timedelta(minutes=minute),
        "open": 100.0,
        "high": 101.0,
        "low": 99.0,
        "close": close,
        "volume": volume,
        "openinterest": 0.0,
    }


@pytest.fixture
def feed():
    item = BtApiFeed(
        dataname="SA609", store=None, timeframe=bt.TimeFrame.Minutes, compression=1
    )
    item.published = []
    original = item._load_bar

    def record(bar):
        item.published.append((bar["datetime"], bar["close"]))
        return original(bar)

    item._load_bar = record
    item.lines.datetime.forward()
    for name in ("open", "high", "low", "close", "volume", "openinterest"):
        getattr(item.lines, name).forward()
    return item


def _drain_history(feed):
    loaded = 0
    while feed._load_history():
        loaded += 1
    return loaded


def test_history_live_overlap_is_deduplicated(feed):
    feed._history = collections.deque([_bar(0), _bar(1), _bar(2)])
    assert _drain_history(feed) == 3
    # Live starts with a bar already delivered by history.
    feed._live = collections.deque([_bar(2), _bar(3)])
    assert feed._load() is True
    assert [when.minute for when, _close in feed.published] == [0, 1, 2, 3]
    assert feed.bar_integrity_counts() == {"duplicates": 1, "late": 0, "revisions_refused": 0}


def test_a_revision_of_a_published_bar_is_refused(feed):
    feed._history = collections.deque([_bar(0, close=100.0), _bar(0, close=105.0), _bar(1)])
    assert _drain_history(feed) == 2
    assert feed.published[0] == (T0, 100.0)  # never silently rewritten
    assert feed.bar_integrity_counts()["revisions_refused"] == 1


def test_late_and_repeated_bars_never_move_the_clock_back(feed):
    feed._history = collections.deque([_bar(0), _bar(2), _bar(1), _bar(2), _bar(3)])
    assert _drain_history(feed) == 3
    assert [when.minute for when, _close in feed.published] == [0, 2, 3]
    assert feed.bar_integrity_counts() == {"duplicates": 1, "late": 1, "revisions_refused": 0}


def test_dropping_bars_does_not_end_the_feed(feed):
    feed._history = collections.deque([_bar(0), _bar(0)])
    assert _drain_history(feed) == 1
    # History exhausted after drops: _load waits for live data instead of
    # reporting end-of-data.
    assert feed._load() is None


def test_tick_timeframe_feeds_are_not_checked():
    item = BtApiFeed(dataname="SA609", store=None, timeframe=bt.TimeFrame.Ticks)
    item.lines.datetime.forward()
    for name in ("open", "high", "low", "close", "volume", "openinterest"):
        getattr(item.lines, name).forward()
    assert item._publish_bar(_bar(0)) is True
    assert item._publish_bar(_bar(0, close=101.0)) is True
    assert item.bar_integrity_counts() == {"duplicates": 0, "late": 0, "revisions_refused": 0}
