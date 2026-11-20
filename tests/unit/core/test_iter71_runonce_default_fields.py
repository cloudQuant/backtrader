"""Runonce default-field and secondary-clock regression coverage."""

from __future__ import annotations

import datetime
import math
import pickle

import pandas as pd
import pytest

import backtrader as bt
import backtrader.linebuffer as linebuffer_module
import backtrader.lineiterator as lineiterator_module
from backtrader.linebuffer import LineActions
from backtrader.lineiterator import LineIterator


def _frame(count, hours, *, offset=0.0):
    index = pd.date_range("2024-01-01", periods=count, freq=f"{hours}h")
    close = [offset + 10.0 + i for i in range(count)]
    return pd.DataFrame(
        {
            "open": close,
            "high": [value + 1.0 for value in close],
            "low": [value - 1.0 for value in close],
            "close": close,
            "volume": [1000.0] * count,
            "openinterest": [0.0] * count,
        },
        index=index,
    )


def _finite_value(line):
    value = float(line[0])
    if not math.isfinite(value):
        return None
    return round(value, 10)


class _LateActionClockStrategy(bt.Strategy):
    """Attach primary and secondary LineActions after indicator setup."""

    def __init__(self):
        self.fast = bt.indicators.SMA(self.data0.close, period=2)
        self.slow = bt.indicators.SMA(self.data1.close, period=2)
        self.fast_action = self.data0.close + 100.0
        self.fast_action.datetime = self.data0.datetime
        self.slow_action = self.data1.close + 200.0
        self.slow_action.datetime = self.data1.datetime
        self.trace = []

    def start(self):
        # Strategy-owned LineActions are normally kept outside the iterator
        # registry. Register prebuilt actions here to exercise late attachment
        # after the strategy's initial indicator-tree setup.
        self.addindicator(self.fast_action)
        self.addindicator(self.slow_action)

    def _capture(self, phase):
        self.trace.append(
            (
                phase,
                len(self.data0),
                len(self.data1),
                len(self.fast),
                len(self.slow),
                len(self.fast_action),
                len(self.slow_action),
                self.fast.lines[0].lencount,
                self.slow.lines[0].lencount,
                self.fast_action.lencount,
                self.slow_action.lencount,
                _finite_value(self.fast),
                _finite_value(self.slow),
                _finite_value(self.fast_action),
                _finite_value(self.slow_action),
            )
        )

    def prenext(self):
        self._capture("prenext")

    def nextstart(self):
        self._capture("nextstart")

    def next(self):
        self._capture("next")


class _PrivateReplayAliasIndicator(bt.Indicator):
    lines = ("_once_called", "_resolved_secondary_clock")

    def next(self):
        self._once_called[0] = 1.0
        self._resolved_secondary_clock[0] = 101.0


class _PrivateReplayAliasStrategy(bt.Strategy):
    def __init__(self):
        self.alias = _PrivateReplayAliasIndicator(self.data0)
        self.trace = []

    def next(self):
        self.trace.append(
            (
                self.alias._once_called[0],
                self.alias._resolved_secondary_clock[0],
            )
        )


def _run_private_alias(runonce):
    cerebro = bt.Cerebro(stdstats=False, runonce=runonce, preload=runonce)
    cerebro.adddata(bt.feeds.PandasData(dataname=_frame(8, 1)))
    cerebro.addstrategy(_PrivateReplayAliasStrategy)
    return cerebro.run()[0]


def _run(runonce):
    cerebro = bt.Cerebro(stdstats=False, runonce=runonce, preload=runonce)
    cerebro.adddata(bt.feeds.PandasData(dataname=_frame(24, 1, offset=0.0)))
    cerebro.adddata(bt.feeds.PandasData(dataname=_frame(6, 4, offset=100.0)))
    cerebro.addstrategy(_LateActionClockStrategy)
    return cerebro.run()[0]


@pytest.mark.parametrize("runonce", (False, True), ids=("runnext", "runonce"))
def test_default_fields_preserve_late_multifeed_indicator_and_action_clocks(runonce):
    strategy = _run(runonce)

    assert len(strategy.trace) == 24
    assert strategy.fast._clock is strategy.data0
    assert strategy.slow._clock is strategy.data1
    assert strategy.slow._resolved_secondary_clock is strategy.data1
    assert strategy.fast._resolved_secondary_clock is None
    assert strategy.fast._once_called is False
    assert strategy.slow._once_called is False
    assert any(item is strategy.fast_action for item in strategy.getindicators())
    assert any(item is strategy.slow_action for item in strategy.getindicators())
    assert isinstance(strategy.fast_action, LineActions)
    assert isinstance(strategy.slow_action, LineActions)
    assert strategy.fast_action._once_called is runonce
    assert strategy.slow_action._once_called is runonce

    for row in strategy.trace:
        (
            _phase,
            fast_len,
            slow_len,
            fast_indicator_len,
            slow_indicator_len,
            fast_action_len,
            slow_action_len,
            fast_indicator_lencount,
            slow_indicator_lencount,
            fast_action_lencount,
            slow_action_lencount,
            _fast_value,
            _slow_value,
            _fast_action_value,
            _slow_action_value,
        ) = row
        assert fast_indicator_len == fast_indicator_lencount == fast_len
        assert slow_indicator_len == slow_indicator_lencount == slow_len
        assert fast_action_len == fast_action_lencount == fast_len
        assert slow_action_len == slow_action_lencount == slow_len

    assert strategy.trace[-1][1:11] == (24, 6, 24, 6, 24, 6, 24, 6, 24, 6)
    assert strategy.trace[-1][11:] == (32.5, 114.5, 133.0, 315.0)


def test_late_multifeed_default_field_trace_matches_both_run_modes():
    runnext = _run(False)
    runonce = _run(True)

    assert runnext.trace == runonce.trace


def test_runonce_default_fields_preserve_legacy_pickled_instance_state():
    strategy = _run(False)
    objects = (
        strategy.fast,
        strategy.slow,
        strategy.fast_action,
        strategy.slow_action,
    )

    # Older instance state has neither replay default in __dict__. Pickle that
    # shape and verify __new__ restores instance defaults on load.
    for obj in objects:
        obj.__dict__.pop("_resolved_secondary_clock", None)
        obj.__dict__.pop("_once_called", None)

    restored = pickle.loads(pickle.dumps(strategy))
    restored_objects = (
        restored.fast,
        restored.slow,
        restored.fast_action,
        restored.slow_action,
    )
    for obj in restored_objects:
        assert obj.__dict__["_resolved_secondary_clock"] is None
        assert obj.__dict__["_once_called"] is False


def test_replay_defaults_are_declared_on_both_scheduler_types():
    for cls in (LineIterator, LineActions):
        assert "_resolved_secondary_clock" not in cls.__dict__
        assert "_once_called" not in cls.__dict__


@pytest.mark.parametrize("runonce", (False, True), ids=("runnext", "runonce"))
def test_private_line_aliases_keep_precedence_over_replay_defaults(runonce):
    strategy = _run_private_alias(runonce)

    assert strategy.trace == [(1.0, 101.0)] * 8
    assert strategy.alias._once_called is strategy.alias.lines.lines[0]
    assert strategy.alias._resolved_secondary_clock is strategy.alias.lines.lines[1]
    assert strategy.alias.__dict__["_once_called"] is strategy.alias.lines.lines[0]
    assert strategy.alias.__dict__["_resolved_secondary_clock"] is strategy.alias.lines.lines[1]


@pytest.mark.parametrize("runonce", (False, True), ids=("runnext", "runonce"))
def test_private_line_aliases_keep_original_behavior_without_replay_defaults(
    runonce, monkeypatch
):
    # The original HEAD had no replay defaults.  Disabling only their new
    # per-instance initialization establishes that the aliases work unchanged
    # in both actual Cerebro scheduling modes.
    def no_defaults(_instance):
        return None

    monkeypatch.setattr(
        linebuffer_module, "_initialize_replay_default_fields", no_defaults
    )
    monkeypatch.setattr(
        lineiterator_module, "_initialize_replay_default_fields", no_defaults
    )

    strategy = _run_private_alias(runonce)

    assert strategy.trace == [(1.0, 101.0)] * 8
    assert strategy.alias._once_called is strategy.alias.lines.lines[0]
    assert strategy.alias._resolved_secondary_clock is strategy.alias.lines.lines[1]
