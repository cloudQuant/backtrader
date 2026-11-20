"""R71-141: unhealthy provider bars never advance a BtApiFeed line."""

from __future__ import annotations

import collections
import datetime as dt

import pytest

pytest.importorskip("bt_api_py.market_tick_contracts")

import backtrader as bt  # noqa: E402
from backtrader.feeds.btapifeed import BtApiFeed  # noqa: E402


T0 = dt.datetime(2026, 11, 20, 9, 0)


def _bar(minute, close, volume, **health):
    return {
        "datetime": T0 + dt.timedelta(minutes=minute),
        "symbol": "SA609",
        "event_id": f"bar-{minute}",
        "open": close - 0.5,
        "high": close + 0.5,
        "low": close - 1.0,
        "close": close,
        "volume": volume,
        "openinterest": 0.0,
        "bar_final": True,
        **health,
    }


class _ScriptedStore:
    """Finite poll_live source; a queued None is an idle poll, not EOF."""

    _market_channels = ("orderbook",)

    def __init__(self, steps):
        self.steps = collections.deque(steps)
        self.poll_trace = []
        self.poll_tick_calls = 0
        self.dropped = []
        self.last_datetime = None

    def start(self, **_kwargs):
        pass

    def register(self, _feed):
        pass

    def subscribe(self, *_args, **_kwargs):
        pass

    def get_notifications(self):
        return []

    def stop(self):
        pass

    def poll_tick(self, _name):
        self.poll_tick_calls += 1

    def poll_live(self, _name):
        if not self.steps:
            self.poll_trace.append(None)
            return None
        step = self.steps.popleft()
        if step is None:
            self.poll_trace.append(None)
            return None
        if isinstance(step, tuple):
            ready, bar = step
            self._ready = ready
            if bar is None:
                self.poll_trace.append(None)
                return None
        else:
            bar = step
        self.last_datetime = bar["datetime"]
        self.poll_trace.append(bar["close"])
        return bar

    def has_pending_live_bar(self, _name):
        return bool(self.steps)

    def is_source_exhausted(self, _name):
        return not self.steps

    def get_source_event_time_watermark(self, _name):
        return self.last_datetime


class _HealthStore(_ScriptedStore):
    def __init__(self, steps):
        super().__init__(steps)
        self._ready = True

    def is_stream_ready(self, _name):
        return self._ready

    def mark_feed_dropped(self, event, reason):
        self.dropped.append((event, reason))


class _HealthProjectionStore(_ScriptedStore):
    def __init__(self, steps):
        super().__init__(steps)
        self._ready = True

    def get_stream_health(self, _name):
        return {
            "stale": not self._ready,
            "continuity_status": "continuous" if self._ready else "gap",
        }


class _BrokenHealthStore(_ScriptedStore):
    def is_stream_ready(self, _name):
        raise RuntimeError("health unavailable")


class _Capture(bt.Strategy):
    def __init__(self):
        self.rows = []
        self.statuses = []
        self.status_rows = []

    def next(self):
        self.rows.append(
            (
                self.data.datetime.datetime(0),
                float(self.data.close[0]),
                float(self.data.volume[0]),
            )
        )

    def notify_data(self, data, status, *args, **kwargs):
        if status in (data.LIVE, data.DELAYED):
            self.statuses.append(status)
            close = float(data.close[0]) if len(data) else None
            self.status_rows.append((status, close))


def _run(store, *, live_bars=None):
    feed = BtApiFeed(
        dataname="SA609",
        store=store,
        timeframe=bt.TimeFrame.Minutes,
        compression=1,
        live_bars=live_bars,
        backfill_start=False,
        qcheck=0.0,
    )
    cerebro = bt.Cerebro(stdstats=False, runonce=False)
    cerebro.adddata(feed)
    cerebro.addstrategy(_Capture)
    (strategy,) = cerebro.run()
    return strategy


def test_sticky_store_health_preserves_poll_fifo_and_none_is_not_eof():
    store = _HealthStore(
        [
            None,
            (True, _bar(0, close=100.0, volume=1.0, continuity_status="continuous")),
            (False, None),
            (False, _bar(0, close=101.0, volume=1000.0, continuity_status="continuous")),
            (False, _bar(1, close=102.0, volume=2000.0, continuity_status="continuous")),
            (True, _bar(2, close=103.0, volume=7.25, continuity_status="continuous")),
            None,
        ]
    )

    strategy = _run(store)

    assert store.poll_trace == [None, 100.0, None, 101.0, 102.0, 103.0, None, None]
    assert [(close, volume) for _when, close, volume in strategy.rows] == [
        (100.0, 1.0),
        (103.0, 7.25),
    ]
    assert strategy.statuses == [
        strategy.data.LIVE,
        strategy.data.DELAYED,
        strategy.data.LIVE,
    ]
    assert strategy.status_rows == [
        (strategy.data.LIVE, 100.0),
        (strategy.data.DELAYED, 100.0),
        (strategy.data.LIVE, 103.0),
    ]
    assert [reason for _event, reason in store.dropped] == [
        "store_stream_not_ready",
        "store_stream_not_ready",
    ]


def test_stale_and_gap_bar_markers_fail_closed_without_optional_store_apis():
    store = _ScriptedStore(
        [
            _bar(0, close=101.0, volume=1000.0, stale=True, continuity_status="gap"),
            _bar(1, close=102.0, volume=8.5, stale=False, continuity_status="continuous"),
            None,
        ]
    )

    strategy = _run(store)

    assert store.poll_trace == [101.0, 102.0, None, None]
    assert [(close, volume) for _when, close, volume in strategy.rows] == [(102.0, 8.5)]
    assert strategy.statuses == [strategy.data.DELAYED, strategy.data.LIVE]


def test_gap_marker_alone_fails_closed_even_when_stale_is_false():
    store = _ScriptedStore(
        [
            _bar(0, close=101.0, volume=1000.0, stale=False, continuity_status="gap"),
            _bar(1, close=102.0, volume=9.25, stale=False, continuity_status="continuous"),
            None,
        ]
    )

    strategy = _run(store)

    assert [(close, volume) for _when, close, volume in strategy.rows] == [(102.0, 9.25)]
    assert strategy.statuses == [strategy.data.DELAYED, strategy.data.LIVE]


def test_store_health_projection_fallback_blocks_until_recovered():
    store = _HealthProjectionStore(
        [
            (False, _bar(0, close=101.0, volume=1000.0, continuity_status="continuous")),
            (True, _bar(1, close=102.0, volume=4.5, continuity_status="continuous")),
            None,
        ]
    )

    strategy = _run(store)

    assert [(close, volume) for _when, close, volume in strategy.rows] == [(102.0, 4.5)]
    assert strategy.statuses == [strategy.data.DELAYED, strategy.data.LIVE]


def test_store_health_api_errors_fail_closed_without_aborting_legacy_feed_loop():
    store = _BrokenHealthStore([_bar(0, close=101.0, volume=1000.0), None])

    strategy = _run(store)

    assert strategy.rows == []
    assert strategy.statuses == [strategy.data.DELAYED]


def test_preloaded_live_bars_preserve_stale_markers_before_cerebro_publication():
    store = _ScriptedStore([])
    strategy = _run(
        store,
        live_bars=[
            _bar(0, close=101.0, volume=1000.0, stale=True, continuity_status="gap"),
            _bar(1, close=102.0, volume=6.0, stale=False, continuity_status="continuous"),
        ],
    )

    assert [(close, volume) for _when, close, volume in strategy.rows] == [(102.0, 6.0)]
    assert strategy.statuses == [strategy.data.DELAYED, strategy.data.LIVE]


def test_duplicate_recovery_marker_does_not_emit_live_before_a_new_bar():
    store = _ScriptedStore(
        [
            _bar(0, close=100.0, volume=1.0, continuity_status="continuous"),
            _bar(1, close=101.0, volume=1000.0, continuity_status="gap"),
            _bar(0, close=100.0, volume=1.0, continuity_status="continuous"),
            _bar(2, close=102.0, volume=2.0, continuity_status="continuous"),
            None,
        ]
    )

    strategy = _run(store)

    assert [(close, volume) for _when, close, volume in strategy.rows] == [
        (100.0, 1.0),
        (102.0, 2.0),
    ]
    assert strategy.statuses == [strategy.data.LIVE, strategy.data.DELAYED, strategy.data.LIVE]
    assert strategy.status_rows == [
        (strategy.data.LIVE, 100.0),
        (strategy.data.DELAYED, 100.0),
        (strategy.data.LIVE, 102.0),
    ]


@pytest.mark.parametrize(
    "health",
    [
        {"stale": None, "continuity_status": "continuous"},
        {"stale": False, "continuity_status": 1},
    ],
    ids=["invalid-stale-marker", "invalid-continuity-marker"],
)
def test_malformed_health_markers_are_rejected_even_without_store_marker_api(health):
    store = _ScriptedStore(
        [
            _bar(0, close=101.0, volume=1000.0, **health),
            _bar(1, close=102.0, volume=5.0, stale=False, continuity_status="continuous"),
            None,
        ]
    )

    strategy = _run(store)

    assert [(close, volume) for _when, close, volume in strategy.rows] == [(102.0, 5.0)]
    assert strategy.statuses == [strategy.data.DELAYED, strategy.data.LIVE]
