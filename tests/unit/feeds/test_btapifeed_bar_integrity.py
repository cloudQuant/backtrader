"""Iteration 60, acceptance report P1-6: published bars are never rewritten.

Provider bars are closed intervals identified by feed + open time. After a
bar is published to the line buffers, a late bar (earlier time), a duplicate
(same time and values, e.g. the history/live overlap) and a revision (same
time, different values) are all dropped and counted; nothing is rewritten.
"""

from __future__ import annotations

import collections
import datetime as dt
from types import MappingProxyType, SimpleNamespace

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
        "bar_final": True,
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
    assert feed.bar_integrity_counts() == {"duplicates": 1, "late": 0, "revisions_refused": 0, "unfinished": 0, "unknown_finality": 0}


def test_a_revision_of_a_published_bar_is_refused(feed):
    feed._history = collections.deque([_bar(0, close=100.0), _bar(0, close=105.0), _bar(1)])
    assert _drain_history(feed) == 2
    assert feed.published[0] == (T0, 100.0)  # never silently rewritten
    assert feed.bar_integrity_counts()["revisions_refused"] == 1


def test_late_and_repeated_bars_never_move_the_clock_back(feed):
    feed._history = collections.deque([_bar(0), _bar(2), _bar(1), _bar(2), _bar(3)])
    assert _drain_history(feed) == 3
    assert [when.minute for when, _close in feed.published] == [0, 2, 3]
    assert feed.bar_integrity_counts() == {"duplicates": 1, "late": 1, "revisions_refused": 0, "unfinished": 0, "unknown_finality": 0}


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
    assert item.bar_integrity_counts() == {"duplicates": 0, "late": 0, "revisions_refused": 0, "unfinished": 0, "unknown_finality": 0}


# -- D60-15 / acceptance report G7: provider finality ---------------------------------


def test_a_forming_provider_bar_is_never_published_only_its_final_version(feed):
    forming = dict(_bar(0, close=100.5), bar_final=False)
    final = dict(_bar(0, close=101.0), bar_final=True)
    feed._live = collections.deque([forming, final, dict(_bar(1), bar_final=None)])
    assert feed._load() is True
    assert feed.published[0] == (T0, 101.0)  # the final values, not the forming ones
    assert feed._load() is None  # unknown finality cannot advance the line
    assert feed.bar_integrity_counts()["unfinished"] == 1
    assert feed.bar_integrity_counts()["unknown_finality"] == 1
    assert feed.bar_integrity_counts()["revisions_refused"] == 0


@pytest.mark.parametrize("unknown", [None, 0, 1, "true"])
def test_unknown_finality_is_not_a_completed_bar(feed, unknown):
    assert not feed._publish_bar(dict(_bar(0), bar_final=unknown))
    assert feed.published == []
    assert feed.bar_integrity_counts()["unknown_finality"] == 1
    # A later explicitly completed version at the same time can be delivered.
    assert feed._publish_bar(_bar(0))


def test_initial_history_and_live_preserve_finality_before_projection():
    history = MappingProxyType(dict(_bar(0), bar_final=False))
    live = MappingProxyType(dict(_bar(1), bar_final=True))
    item = BtApiFeed(
        dataname="SA609", store=None, timeframe=bt.TimeFrame.Minutes,
        historical_bars=[history], live_bars=[live],
    )
    assert item._history[0]["bar_final"] is False
    assert item._live[0]["bar_final"] is True


def test_completed_local_aggregation_marks_its_queued_bar(feed):
    feed.p.dispatch_bars = False
    event = SimpleNamespace(open=100, high=101, low=99, close=100, volume=1, openinterest=0)
    feed._enqueue_bar_event(event, T0)
    assert feed._live[0]["bar_final"] is True
    assert feed._load() is True
    assert feed.published == [(T0, 100.0)]


def test_history_projection_preserves_completion_and_unknown():
    from bt_api_base.market_history_protocol import MarketBar
    from backtrader.stores._bar_history_cache import StoreBarHistoryCache
    from backtrader.utils.bar_projection import normalize_bar

    cache = StoreBarHistoryCache(preserve_raw_bars=False, normalize_bar=normalize_bar)
    assert cache.copy_or_normalize_bar(dict(_bar(0), bar_final=False))["bar_final"] is False
    unknown = dict(_bar(0))
    del unknown["bar_final"]
    assert "bar_final" not in cache.copy_or_normalize_bar(unknown)
    typed = MarketBar(
        open_time_utc="2026-11-03T09:00:00Z", close_time_utc="2026-11-03T09:01:00Z",
        open="100", high="101", low="99", close="100", volume="1",
    )
    (projected,) = cache.project_market_bars((typed,))
    assert projected["bar_final"] is True
    assert cache.copy_or_normalize_bar(projected)["bar_final"] is True


def test_service_history_projection_keeps_typed_bar_completion():
    from bt_api_base.market_history_protocol import MarketBar
    from backtrader.service.service_read_proxy import _bar_to_dict

    typed = MarketBar(
        open_time_utc="2026-11-03T09:00:00Z", close_time_utc="2026-11-03T09:01:00Z",
        open="100", high="101", low="99", close="100", volume="1",
    )
    assert _bar_to_dict(typed)["bar_final"] is True


def test_store_dispatch_drops_forming_provider_bars():
    from types import SimpleNamespace

    from backtrader.service.store_event_dispatch import drain_store_sdk_events_locked

    counted, accepted = [], []

    class _Api:
        def poll_events(self, venue, **_kwargs):
            return [
                {"kind": "bar", "symbol": "SA609", "bar_final": False, "close": 1.0},
                {"kind": "bar", "symbol": "SA609", "bar_final": True, "close": 2.0},
            ]

    store = SimpleNamespace(
        _sdk_exchanges=["SIM"],
        _api=_Api(),
        _sdk_event_batch_size=10,
        _sdk_coalesce_market_snapshots=(),
        uses_async_commands=False,
        _subscribed_datanames={"SA609"},
        _sdk_exchange=lambda symbol: "SIM",
        _record_sdk_market_event=lambda venue, event: event,
        _market_delivery_state=SimpleNamespace(increment=lambda s, k: counted.append(k)),
        _accept_sdk_market_event=lambda event, raw: accepted.append(event["close"]),
        _enqueue_live_bar=lambda symbol, bar: None,
        _copy_or_normalize_bar=lambda bar: bar,
        emit_runtime_event=lambda *a, **k: None,
    )
    drain_store_sdk_events_locked(
        store, error_type=RuntimeError, missing_dependency_error_type=ImportError
    )
    assert counted == ["unfinished_provider_bar"] and accepted == [2.0]


@pytest.mark.parametrize(
    "raw, expected",
    [(True, True), (False, False), (1, True), (0, False), ("1", True), ("false", False), (None, None), ("x", None)],
)
def test_sdk_bar_events_carry_provider_finality(raw, expected):
    from bt_api_py._normalization import _bar_final

    assert _bar_final(raw) is expected
