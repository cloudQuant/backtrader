"""Iteration 71 Batch 7 regression coverage for R71-100, R71-101, R71-102, R71-104."""

from __future__ import annotations

import math
import pickle
from types import SimpleNamespace
import weakref

import pandas as pd
import pytest

import backtrader as bt
from backtrader.indicator import _resolve_indicator_advance_clock
from backtrader.linebuffer import LineActions, LineBuffer, _factor_context_for_line
from backtrader.lineiterator import LineIterator
from backtrader.lineseries import Lines, MinimalClock


def _make_frame(count: int, freq: str = "1h", offset: float = 0.0) -> pd.DataFrame:
    index = pd.date_range("2024-01-01", periods=count, freq=freq)
    close = [offset + 20.0 + (i * 1.5) + ((i % 5) * 0.25) for i in range(count)]
    return pd.DataFrame(
        {
            "open": [c - 0.5 for c in close],
            "high": [c + 1.25 for c in close],
            "low": [c - 1.25 for c in close],
            "close": close,
            "volume": [1000.0 + (i * 10.0) for i in range(count)],
            "openinterest": [0.0] * count,
        },
        index=index,
    )


def _norm(val: float):
    v = float(val)
    return None if not math.isfinite(v) else round(v, 10)


class _VaryingPrivateAliasIndicator(bt.Indicator):
    """Indicator whose line aliases collide with internal replay attribute names."""

    lines = ("_once_called", "_resolved_secondary_clock", "_bt_resolved_secondary_clock")

    def next(self):
        c = self.data.close[0]
        self.lines._once_called[0] = c * 2.0
        self.lines._resolved_secondary_clock[0] = c + 100.0
        self.lines._bt_resolved_secondary_clock[0] = c - 50.0


class _EquivalenceStrategy(bt.Strategy):
    def __init__(self):
        self.sma_fast = bt.indicators.SMA(self.data0.close, period=3)
        self.ema_fast = bt.indicators.EMA(self.data0.close, period=4)
        self.sma_slow = bt.indicators.SMA(self.data1.close, period=2)
        self.expr_ind = bt.indicators.SMA(self.data0.high - self.data0.low, period=3)
        self.alias_ind = _VaryingPrivateAliasIndicator(self.data0)
        self.records = []

    def _record(self, phase: str):
        self.records.append(
            (
                phase,
                len(self),
                len(self.data0),
                len(self.data1),
                len(self.sma_fast),
                len(self.ema_fast),
                len(self.sma_slow),
                len(self.expr_ind),
                len(self.alias_ind),
                _norm(self.sma_fast[0]),
                _norm(self.ema_fast[0]),
                _norm(self.sma_slow[0]),
                _norm(self.expr_ind[0]),
                _norm(self.alias_ind._once_called[0]),
                _norm(self.alias_ind._resolved_secondary_clock[0]),
                _norm(self.alias_ind._bt_resolved_secondary_clock[0]),
            )
        )

    def prenext(self):
        self._record("prenext")

    def nextstart(self):
        self._record("nextstart")

    def next(self):
        self._record("next")


def test_r71_101_runonce_and_runnext_full_sequence_numerical_equivalence():
    """Full bar-by-bar parity between runonce=True and runonce=False, including colliding line names."""
    df_fast = _make_frame(32, freq="1h", offset=0.0)
    df_slow = _make_frame(8, freq="4h", offset=200.0)

    results = {}
    for runonce in (False, True):
        cerebro = bt.Cerebro(stdstats=False, runonce=runonce, preload=runonce)
        cerebro.adddata(bt.feeds.PandasData(dataname=df_fast))
        cerebro.adddata(bt.feeds.PandasData(dataname=df_slow))
        cerebro.addstrategy(_EquivalenceStrategy)
        results[runonce] = cerebro.run()[0]

    strat_next = results[False]
    strat_once = results[True]
    assert len(strat_next.records) == 32
    assert strat_next.records == strat_once.records
    # Verify varying values on colliding line aliases advanced properly on every bar
    alias_once_vals = [row[13] for row in strat_once.records]
    assert len(set(alias_once_vals)) == 32


def test_r71_101_oncepost_lencount_dynamic_topology():
    """Strategy._oncepost tracks changed indicators and lines without losing synchronization."""
    df = _make_frame(12, freq="1h")

    class _DynamicOncepostStrategy(bt.Strategy):
        def __init__(self):
            self.sma = bt.indicators.SMA(self.data.close, period=2)
            self.action = self.data.close + 10.0
            self.action.datetime = self.data.datetime
            self.extra_line = LineBuffer()
            self.snapshots = []

        def start(self):
            self.addindicator(self.action)

        def next(self):
            bar = len(self)
            if bar == 4:
                # Dynamically attach a new line to self.action.lines.lines
                self.action.lines.lines.append(self.extra_line)
            elif bar == 6:
                # Dynamically toggle _once_called on self.sma so its lines join the sync plan
                self.sma._once_called = True
            elif bar == 8:
                # Dynamically replace self.action.lines with a fresh Lines container
                replacement_lines = Lines()
                replacement_buf = LineBuffer()
                replacement_lines.lines = [replacement_buf]
                self.action.lines = replacement_lines
                self.replacement_buf = replacement_buf
            self.snapshots.append(
                (
                    bar,
                    self.action.lencount,
                    self.extra_line.lencount,
                    self.sma.lines[0].lencount,
                    getattr(self, "replacement_buf", self.extra_line).lencount,
                )
            )

    cerebro = bt.Cerebro(stdstats=False, runonce=True, preload=True)
    cerebro.adddata(bt.feeds.PandasData(dataname=df))
    cerebro.addstrategy(_DynamicOncepostStrategy)
    strat = cerebro.run()[0]

    # At bar 5 (after bar 4 mutation), extra_line must have been synced to strategy length (5)
    bar5 = next(row for row in strat.snapshots if row[0] == 5)
    assert bar5[2] == 5
    # At bar 9 (after bar 8 lines replacement), replacement_buf must have been synced to 9
    bar9 = next(row for row in strat.snapshots if row[0] == 9)
    assert bar9[4] == 9


def test_r71_101_minimal_clock_fallback_cache_and_invalidation():
    """_resolve_indicator_advance_clock caches MinimalClock fallback and invalidates on _clock/datas change."""
    df1 = _make_frame(6, freq="1h")
    df2 = _make_frame(6, freq="1h", offset=50.0)
    feed1 = bt.feeds.PandasData(dataname=df1)
    feed2 = bt.feeds.PandasData(dataname=df2)

    class _ProbeInd(bt.Indicator):
        lines = ("val",)

    ind = LineIterator.__new__(_ProbeInd)
    ind.datas = [feed1]
    ind._clock = MinimalClock()

    resolved1 = _resolve_indicator_advance_clock(ind)
    assert resolved1 is feed1
    cache1 = ind.__dict__.get("_bt_resolved_secondary_clock")
    assert isinstance(cache1, tuple) and cache1[2] is feed1

    # Cache hit returns identical feed1
    assert _resolve_indicator_advance_clock(ind) is feed1

    # Dynamically replacing datas[0] invalidates the cache immediately
    ind.datas = [feed2]
    resolved2 = _resolve_indicator_advance_clock(ind)
    assert resolved2 is feed2
    assert ind.__dict__["_bt_resolved_secondary_clock"][2] is feed2

    # Dynamically replacing _clock with a concrete clock bypasses MinimalClock fallback
    ind._clock = feed1
    assert _resolve_indicator_advance_clock(ind) is feed1


def test_r71_100_and_r71_102_dynamic_class_context_on_standard_objects(monkeypatch):
    """Contexts added to standard object classes remain visible after earlier lookups."""
    df = _make_frame(10, freq="1h")

    class _CheckStrat(bt.Strategy):
        def __init__(self):
            self.sma = bt.indicators.SMA(self.data.close, period=3)

    cerebro = bt.Cerebro(stdstats=False, runonce=False)
    cerebro.adddata(bt.feeds.PandasData(dataname=df))
    cerebro.addstrategy(_CheckStrat)
    strat = cerebro.run()[0]
    ind = strat.sma
    line = ind.lines[0]

    assert _factor_context_for_line(line) is None
    assert ind._factor_strict_context_for_callback() is None
    assert strat._factor_strict_context_for_callback() is None

    marker = object()
    with monkeypatch.context() as patch:
        patch.setattr(type(strat), "_factor_strict_context", marker, raising=False)
        assert strat._factor_strict_context_for_callback() is marker
        assert ind._factor_strict_context_for_callback() is marker
        assert _factor_context_for_line(line) is marker
    assert ind._factor_strict_context_for_callback() is None
    assert _factor_context_for_line(line) is None

    with monkeypatch.context() as patch:
        patch.setattr(type(ind), "_factor_strict_context", marker, raising=False)
        assert ind._factor_strict_context_for_callback() is marker
        assert _factor_context_for_line(line) is marker
    assert ind._factor_strict_context_for_callback() is None

    with monkeypatch.context() as patch:
        patch.setattr(type(line), "_factor_strict_context", marker, raising=False)
        assert _factor_context_for_line(line) is marker
    assert _factor_context_for_line(line) is None


class _PickleProbeStrategy(bt.Strategy):
    def __init__(self):
        self.sma = bt.indicators.SMA(self.data.close, period=3)


def test_r71_100_and_r71_102_late_attachment_deep_chain_and_pickle_fallback():
    """Late-attached contexts on self, owner, or deep ancestors and unpickled objects resolve properly."""
    df = _make_frame(10, freq="1h")

    cerebro = bt.Cerebro(stdstats=False, runonce=False)
    cerebro.adddata(bt.feeds.PandasData(dataname=df))
    cerebro.addstrategy(_PickleProbeStrategy)
    strat = cerebro.run()[0]
    ind = strat.sma
    line = ind.lines[0]

    # A first lookup must not prevent a later owner context from being observed.
    assert ind._factor_strict_context_for_callback() is None

    # Late-attach context on strategy (owner of ind).
    strat_ctx = object()
    strat._factor_strict_context = strat_ctx
    assert ind._factor_strict_context_for_callback() is strat_ctx
    assert _factor_context_for_line(line) is strat_ctx

    # Late-attach context on indicator itself -> takes precedence over strategy context
    ind_ctx = object()
    ind._factor_strict_context = ind_ctx
    assert ind._factor_strict_context_for_callback() is ind_ctx
    assert _factor_context_for_line(line) is ind_ctx

    # Clear contexts and attach a 4-hop ancestor chain to test >3 hop fallback
    ind._factor_strict_context = None
    strat._factor_strict_context = None
    assert ind._factor_strict_context_for_callback() is None

    root_ctx = object()
    hop4 = SimpleNamespace(_factor_strict_context=root_ctx, _owner=None)
    hop3 = SimpleNamespace(_factor_strict_context=None, _owner=hop4)
    hop2 = SimpleNamespace(_factor_strict_context=None, _owner=hop3)
    strat._owner = hop2
    assert ind._factor_strict_context_for_callback() is root_ctx
    assert _factor_context_for_line(line) is root_ctx

    # Dead weakref proxy returns active context gracefully
    class _WeakNode:
        def __init__(self, ctx):
            self._factor_strict_context = ctx

    temp = _WeakNode(root_ctx)
    proxy = weakref.proxy(temp)
    assert _factor_context_for_line(proxy) is root_ctx
    del temp
    assert _factor_context_for_line(proxy) is None

    # Legacy pickled state without new dict defaults restores cleanly
    strat._owner = None
    for obj in (strat, ind, line):
        obj.__dict__.pop("_factor_strict_context", None)
        obj.__dict__.pop("_bt_factor_cb_cache", None)
    restored = pickle.loads(pickle.dumps(strat))
    assert restored.sma._factor_strict_context_for_callback() is None
    assert _factor_context_for_line(restored.sma.lines[0]) is None


def _make_clock_strategy():
    df1 = _make_frame(8, freq="1h")
    df2 = _make_frame(8, freq="1h", offset=100.0)

    class _ClkStrat(bt.Strategy):
        def __init__(self):
            self.ind_buf = bt.indicators.SMA(self.data0.close, period=2)
            self.ind_feed = bt.indicators.SMA(self.data0, period=2)
            self.expr = self.data0.close + 5.0
            self.ind_la = bt.indicators.SMA(self.expr, period=2)

    cerebro = bt.Cerebro(stdstats=False, runonce=False)
    cerebro.adddata(bt.feeds.PandasData(dataname=df1))
    cerebro.adddata(bt.feeds.PandasData(dataname=df2))
    cerebro.addstrategy(_ClkStrat)
    return cerebro.run()[0]


def test_r71_104_clk_update_dynamic_sources():
    """Clock changes and an explicitly invalidated action cache are observed."""
    strat = _make_clock_strategy()
    assert isinstance(strat.expr, LineActions)

    # A changed LineBuffer clock is used on the next update.
    strat.data0.close._clock = strat.data1
    strat.ind_buf._clk_update()
    assert strat.ind_buf._clock is strat.data1

    # LineActions clock changes are observed immediately without stale caching.
    strat.expr._clock = strat.data1
    strat.ind_la._clk_update()
    assert strat.ind_la._clock is strat.data1
    assert "_lineaction_source_clock_cache" not in strat.expr.__dict__

    # A replacement first data supplies the new clock.
    strat.ind_feed.datas = [strat.data1]
    strat.data1._clock = strat.data1
    strat.ind_feed._clk_update()
    assert strat.ind_feed._clock is strat.data1

    # Emptying datas leaves no iterator-level cache.
    strat.ind_feed.datas = []
    strat.ind_feed._clk_update()
    assert strat.ind_feed.__dict__.get("_bt_clk_update_cache") is None


def test_r71_104_lineaction_clock_change_without_explicit_invalidation():
    """LineActions clock reassignment updates downstream indicator clock immediately."""
    strat = _make_clock_strategy()
    assert "_lineaction_source_clock_cache" not in strat.expr.__dict__
    strat.expr._clock = strat.data1
    strat.ind_la._clk_update()
    assert strat.ind_la._clock is strat.data1
